import json
import logging

import requests
import streamlit as st

st.title("Athena")

# Configure logging
app_logger = logging.getLogger()
app_logger.addHandler(logging.StreamHandler())
app_logger.setLevel(logging.INFO)

# File uploader
uploaded_files = st.file_uploader("Upload your lecture slides (PDF)",
                                  type=["pdf"], accept_multiple_files=True)

# Get use cases from backend
try:
    use_cases = requests.get("http://localhost:8000/use_cases").json()
except requests.exceptions.RequestException:
    st.error("Failed to fetch use cases from the backend.")
    use_cases = []

mode = st.selectbox("What do you want Athena to generate?", use_cases, format_func=lambda x: x["name"])

if uploaded_files:
    files = [("files", (f.name, f.getvalue(), "application/pdf")) for f in uploaded_files]
    with st.spinner("Processing"):
        response = requests.post("http://localhost:8000/process_files", files=files)
        if response.status_code != 200:
            st.error(f"Error: {response.status_code}")

generate_button = st.button("Generate", type="primary")

# Initialize session state for generated output
if 'generated_output' not in st.session_state:
    st.session_state.generated_output = None

download_container = st.container()

if generate_button:
    if uploaded_files:
        data = {"mode": mode["id"]}
        # Convert the uploaded files into a format suitable for requests
        file_data = [("files", (f.name, f.getvalue(), "application/pdf")) for f in uploaded_files]

        stream_mode = True
        with st.spinner("Processing your request..."):
            try:
                message_placeholder = st.empty()
                full_response = ""

                if stream_mode:
                    with requests.post(
                            "http://localhost:8000/process_stream",
                            data=data,
                            files=file_data,
                            stream=True
                    ) as response:
                        if response.status_code == 200:
                            for line in response.iter_lines():
                                if line:
                                    try:
                                        chunk = json.loads(line)
                                        full_response += chunk["content"]

                                        # Process the full response for Markdown rendering
                                        split_content = full_response.split('$$')  # Assuming LaTeX is enclosed in $$
                                        formatted_parts = []
                                        for i, part in enumerate(split_content):
                                            if i % 2 == 0:
                                                # Ensure proper Markdown formatting
                                                formatted_parts.append(part.strip())
                                            else:
                                                # Process LaTeX parts
                                                formatted_parts.append(f"$$ {part.strip()} $$")

                                        # Join all parts and add newlines for proper formatting
                                        formatted_response = "\n\n".join(formatted_parts)
                                        message_placeholder.markdown(formatted_response, unsafe_allow_html=True)

                                    except json.JSONDecodeError:
                                        continue

                            st.session_state.generated_output = full_response
                            with download_container:
                                st.download_button(
                                    label="Download Output",
                                    data=full_response,
                                    file_name="generated_output.md",
                                    mime="text/markdown",
                                    key=f"download_button_{hash(full_response)}"
                                )
                        else:
                            st.error(f"Error: {response.status_code}")

                else:
                    # Non-streaming mode
                    response = requests.post("http://localhost:8000/process", data=data, files=file_data)
                    if response.status_code == 200:
                        response_json = response.json()
                        full_response = response_json["output"]

                        split_content = full_response.split('$$')
                        for i, part in enumerate(split_content):
                            if i % 2 == 0:
                                message_placeholder.markdown(part, unsafe_allow_html=True)
                            else:
                                st.latex(part.strip())

                        st.session_state.generated_output = full_response
                        with download_container:
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
