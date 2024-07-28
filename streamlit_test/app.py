import streamlit as st
import requests
import time

st.set_page_config(page_title="Smart Library", page_icon="🤖")
st.title("Smart Library")

def send_message(user_input):
    response = requests.post("http://localhost:8000/chat", json={"query": user_input}, stream=True)
    return response

if "history" not in st.session_state:
    st.session_state.history = []

for message in st.session_state.history:
    if message["type"] == "user":
        with st.chat_message("Human"):
            st.write(message["content"])
    elif message["type"] == "bot":
        with st.chat_message("AI"):
            st.write(message["content"])

user_input = st.chat_input("Type your message here...")
if user_input:
    st.session_state.history.append({"type": "user", "content": user_input})
    with st.chat_message("Human"):
        st.write(user_input)

    with st.chat_message("AI"):
        ai_message_placeholder = st.empty()

    response_stream = send_message(user_input)
    full_response = ""
    for chunk in response_stream.iter_content(chunk_size=512):
        try:
            chunk_str = chunk.decode("utf-8")
        except UnicodeDecodeError:
            continue
        full_response += chunk_str
        ai_message_placeholder.markdown(full_response.strip())

    st.session_state.history.append({"type": "bot", "content": full_response.strip()})
