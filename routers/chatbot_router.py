from fastapi import APIRouter, Depends

from auth.clerk_auth import get_current_user
from models.auth_model import UserContext
from models.chatbot_model import AskRequest, AskResponse
from services import chatbot_indexer, chatbot_service

router = APIRouter(prefix="/chatbot", tags=["Chatbot"])


@router.post("/ask", response_model=AskResponse)
def ask(request: AskRequest, _: UserContext = Depends(get_current_user)):
    return chatbot_service.answer(request)


@router.get("/health")
def health(_: UserContext = Depends(get_current_user)):
    return chatbot_indexer.index_stats()


@router.post("/reindex")
def reindex(_: UserContext = Depends(get_current_user)):
    chatbot_indexer.build_index()
    stats = chatbot_indexer.index_stats()
    return {"rebuilt": True, "chunk_count": stats["indexed_chunks"]}
