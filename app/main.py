from fastapi import FastAPI
from app.api.routes import router

app = FastAPI(
    title="CSSA AI Chatbot API",
    version="0.1.0"
)

app.include_router(router)

@app.get("/")
def root():
    return {"message": "CSSA AI Chatbot API is running"}


@app.get("/health")
def health_check():
    return {"status": "ok"}