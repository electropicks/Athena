echo "Starting backend and frontend" && ((cd src/backend/ && uvicorn main:app --reload) & (streamlit run src/frontend/app.py))
