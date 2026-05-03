from models.chatbot_model import AskRequest, AskResponse, MatchedSection
from services.chatbot_indexer import search, index_stats

_MIN_SCORE = 0.30  # cosine similarity — 0–1 scale
_MAX_CHUNK_DISPLAY = 1200
_FALLBACK = (
    "I can only answer questions about AI Music Gen features. "
    "Could you rephrase? Topics I know about: "
    "Generation, Editing, Production, Account & Workspace."
)
_ENGLISH_ONLY = (
    "I currently only support questions in English. "
    "Please rephrase your question in English and I'll be happy to help."
)


def _ascii_ratio(text: str) -> float:
    if not text:
        return 0.0
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    ascii_letters = [c for c in letters if ord(c) < 128]
    return len(ascii_letters) / len(letters)


def answer(request: AskRequest) -> AskResponse:
    question = request.question.strip()

    if _ascii_ratio(question) < 0.6:
        return AskResponse(
            answer=_ENGLISH_ONLY,
            matched_sections=[],
            confidence=0.0,
            grounded=False,
        )

    results = search(question, top_k=3)

    if not results:
        return AskResponse(
            answer=_FALLBACK,
            matched_sections=[],
            confidence=0.0,
            grounded=False,
        )

    top_score = results[0][1]

    if top_score < _MIN_SCORE:
        matched = [
            MatchedSection(heading=c.heading, category=c.category, score=round(s, 3))
            for c, s in results
        ]
        return AskResponse(
            answer=_FALLBACK,
            matched_sections=matched,
            confidence=round(top_score, 3),
            grounded=False,
        )

    top_chunk, top_score_val = results[0]
    body = top_chunk.text
    # strip the heading line from body for display (it's surfaced via matched_sections)
    lines = body.splitlines()
    body_lines = [l for l in lines if not l.startswith("### ")]
    body_text = "\n".join(body_lines).strip()
    if len(body_text) > _MAX_CHUNK_DISPLAY:
        body_text = body_text[:_MAX_CHUNK_DISPLAY].rsplit(" ", 1)[0] + "…"

    related_parts = [c.heading for c, _ in results[1:] if c.heading != top_chunk.heading]
    related_line = ""
    if related_parts:
        related_line = f"\n\nRelated: {', '.join(related_parts)}."

    answer_text = f"Here's what I found about **{top_chunk.heading}**:\n\n{body_text}{related_line}"

    matched = [
        MatchedSection(heading=c.heading, category=c.category, score=round(s, 3))
        for c, s in results
    ]

    return AskResponse(
        answer=answer_text,
        matched_sections=matched,
        confidence=round(top_score_val, 3),
        grounded=True,
    )
