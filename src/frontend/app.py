import json
import logging
from logging import getLogger
from tempfile import NamedTemporaryFile

import requests
import streamlit as st
from bs4 import BeautifulSoup, NavigableString

from pdf_utils import extract_markdown_from_pdf

# Configure logging
app_logger = getLogger()
app_logger.addHandler(logging.StreamHandler())
app_logger.setLevel(logging.INFO)

st.title("Athena")

# Initialize session state for generated output
if 'generated_output' not in st.session_state:
    st.session_state.generated_output = None

# File uploader
uploaded_files = st.file_uploader("Upload your lecture slides (PDF)", type=["pdf"], accept_multiple_files=True)

# Extract context from uploaded files
context_files = []
for uploaded_file in uploaded_files:
    if uploaded_file is not None:
        with NamedTemporaryFile(suffix="pdf") as temp:
            temp.write(uploaded_file.getvalue())
            temp.seek(0)
            context_files.append(extract_markdown_from_pdf(temp.name))

# Get use cases from backend
try:
    use_cases = [dict(item) for item in requests.get("http://localhost:8000/use_cases").json()]
except requests.exceptions.RequestException:
    st.error("Failed to fetch use cases from the backend.")
    use_cases = []

# Dropdown for use cases
mode = st.selectbox("What do you want Athena to generate?", use_cases, format_func=lambda x: x["name"])

# Arrange buttons in a single row using columns
generate_button = st.button("Generate", type="primary")

# Process when "Generate" button is clicked
if generate_button:
    if len(context_files) > 0:
        parsedFileMarkdownInput = "\n --- \n".join(context_files)
        data = {"mode": mode["id"], "uploaded_context": parsedFileMarkdownInput}

        with st.spinner("Processing your request..."):
            try:
                # Create a placeholder for the streaming content
                message_placeholder = st.empty()
                full_response = ""

                # Make streaming request
                with requests.post(
                        "http://localhost:8000/process_stream",
                        data=data,
                        stream=True
                ) as response:
                    if response.status_code == 200:
                        for line in response.iter_lines():
                            if line:
                                try:
                                    chunk = json.loads(line)
                                    full_response += chunk["content"]
                                    # Update the placeholder with the accumulated response
                                    message_placeholder.markdown(full_response)
                                except json.JSONDecodeError:
                                    continue

                        # Store the complete response in session state
                        st.session_state.generated_output = full_response

                        # Add download button after completion
                        st.download_button(
                            label="Download Output",
                            data=full_response,
                            file_name="generated_output.md",
                            mime="text/markdown"
                        )
                    else:
                        st.error(f"Error: {response.status_code}")
            except requests.exceptions.RequestException as e:
                st.error(f"Request failed: {str(e)}")
    else:
        st.warning("Please upload at least one file.")