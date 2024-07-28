from sqlalchemy.orm import Session
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage, AIMessage
from langchain.prompts import ChatPromptTemplate
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_chroma import Chroma
import re
from app.common.database.database import get_db
from app.schemas.chat import AgentState
from app.common.database.models import Book, Author
from langchain_core.chat_history import BaseChatMessageHistory, InMemoryChatMessageHistory
from langchain_ollama.llms import OllamaLLM
from app.utils.prompts import main_template, intent_template

# Initialize models and embeddings
embeddings = HuggingFaceEmbeddings()
db_chroma = Chroma(persist_directory="./chroma_db", embedding_function=embeddings)

# model = OllamaLLM(model="llama3.1:8b")
# intent_model = OllamaLLM(model="llama3.1:8b") testing different llms
model = ChatOpenAI(model="gpt-4o-mini", api_key="API-KEY")
intent_model = ChatOpenAI(model="gpt-4o-mini", api_key="API-KEY")

main_prompt = ChatPromptTemplate.from_template(main_template)
intent_prompt = ChatPromptTemplate.from_template(intent_template)

main_chain = main_prompt | model
intent_chain = intent_prompt | intent_model

store = {}

def get_session_history(session_id: str) -> BaseChatMessageHistory:
    if session_id not in store:
        store[session_id] = InMemoryChatMessageHistory()
    return store[session_id]

main_with_message_history = RunnableWithMessageHistory(
    runnable=main_chain,
    get_session_history=get_session_history
)

intent_with_message_history = RunnableWithMessageHistory(
    runnable=intent_chain,
    get_session_history=get_session_history
)

def detect_intent(state):
    intent_input = state['messages'][-1].content
    config = {"configurable": {"session_id": "detect_intent_session"}}
    intent_response = intent_with_message_history.invoke([HumanMessage(content=intent_input)], config=config)
    intent = intent_response.content.strip().lower().split()[0]
    if intent == "unknown":
        response = AIMessage(content="I'm sorry, I can only answer questions that relate to book recommendations, finding books that relate to a description, top books in a specific genre, or adding a book to the database.")
        return {"messages": [response], "intent": "unknown"}
    return {"intent": intent.strip('"')}

def book_recommendation(state):
    human_input = state['messages'][-1].content
    context = retrieve(human_input)
    combined_input = f"Context: {context}\n\n Human Message: {human_input}"

    config = {"configurable": {"session_id": "book_recommendation_session"}}
    response = main_with_message_history.invoke([HumanMessage(content=combined_input)], config=config)
    
    response_message = response.content
    
    return {"messages": state['messages'] + [AIMessage(content=response_message)]}

def top_books_genre(state, db: Session):
    message_content = state['messages'][-1].content.lower()
    match = re.search(r"top (\d+) books in (.+)", message_content, re.IGNORECASE)
    if match:
        k = int(match.group(1))
        genre = match.group(2).strip()
        top_books = db.query(Book).filter(Book.genre.ilike(f"%{genre}%")).order_by(Book.average_rating.desc()).limit(k).all()
        if top_books:
            response_content = f"Here are the top {k} books in the genre '{genre}':\n"
            for book in top_books:
                response_content += f"- {book.title} by {book.author.name} (Rating: {book.average_rating})\n"
        else:
            response_content = f"No books found in the genre '{genre}'."
        response = AIMessage(content=response_content)
    else:
        response = AIMessage(content="Please specify the number of top books and the genre.")
    return {"messages": state['messages'] + [response]}

def add_book(state, db: Session):
    message_content = state['messages'][-1].content
    # Simplify the regex pattern to match the book details
    match = re.search(
        r'add book titled "(.+?)" by (.+?), genre: (.+?), description: (.+?), rating: (\d+(\.\d+)?), published in (\d{4})',
        message_content, re.IGNORECASE
    )
    
    # Debugging: Print the matched groups
    print(f"Message Content: {message_content}")
    print(f"Match: {match.groups() if match else 'No match found'}")
    
    if match:
        title, author_name, genre, description, average_rating, _, published_year = match.groups()
        
        # Check if the author exists
        author = db.query(Author).filter(Author.name.ilike(author_name.strip())).first()
        
        if author:
            new_book = Book(
                title=title,
                author_id=author.author_id,  # Use the existing author's ID
                genre=genre,
                description=description,
                average_rating=float(average_rating),
                published_year=int(published_year)
            )
            db.add(new_book)
            db.commit()
            response_content = f"Book '{title}' by {author_name} added successfully."
        else:
            response_content = f"Author '{author_name}' does not exist in the database. Please add the author first."
    else:
        response_content = (
            "Please provide all the required information: "
            'title, author, genre, description, rating, and published year. '
            'The correct format is: add book titled "BOOK_TITLE" by AUTHOR_NAME, genre: GENRE, '
            'description: DESCRIPTION, rating: RATING, published in YEAR.'
        )
    
    response = AIMessage(content=response_content)
    return {"messages": state['messages'] + [response]}



workflow = StateGraph(AgentState)

workflow.add_node("detect_intent", detect_intent)
workflow.add_node("book_recommendation", book_recommendation)

def top_books_genre_node(state):
    with next(get_db()) as db:
        return top_books_genre(state, db)

def add_book_node(state):
    with next(get_db()) as db:
        return add_book(state, db)

workflow.add_node("top_books_genre", top_books_genre_node)
workflow.add_node("add_book", add_book_node)

workflow.set_entry_point("detect_intent")

workflow.add_conditional_edges(
    "detect_intent",
    lambda state: state["intent"],
    {
        "book_recommendation": "book_recommendation",
        "top_books_genre": "top_books_genre",
        "add_book": "add_book",
        "unknown": END,
    }
)

app_graph = workflow.compile()


def retrieve(query):
    docs = db_chroma.similarity_search(query)
    retrieved_docs = [doc.page_content for doc in docs]
    return retrieved_docs
