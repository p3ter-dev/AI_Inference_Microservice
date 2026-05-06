"""
AI Inference gRPC Server
Implements all four gRPC communication patterns backed by Google Gemini.
Includes:
  - Auth interceptor (Bearer token validation)
  - Deadline-aware unary handler (intentional 3-second sleep for demo)
"""

import asyncio
import json
import logging
import os
import re
from typing import AsyncIterator

import grpc
from grpc import aio

import ai_inference_pb2 as pb2
import ai_inference_pb2_grpc as pb2_grpc

import google.generativeai as genai

# ──────────────────────────────────────────────
#  Configuration
# ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
)
log = logging.getLogger("ai_inference_server")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
API_SECRET_KEY = os.environ.get("API_SECRET_KEY", "my-secret-key")
PORT           = int(os.environ.get("GRPC_PORT", "50051"))

#  Gemini Client Setup

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    _model = genai.GenerativeModel("gemini-2.5-flash-lite")
else:
    log.warning("GEMINI_API_KEY not set – using stub responses.")
    _model = None


async def _gemini_generate(prompt: str, stream: bool = False):
    """Thin async wrapper around the Gemini SDK."""
    if _model is None:
        if stream:
            for word in f"[STUB] Response for: {prompt[:60]}".split():
                yield word + " "
            return
        else:
            yield f"[STUB] Response for: {prompt[:80]}"

    if stream:
        response = await asyncio.to_thread(
            _model.generate_content, prompt,
            stream=True
        )
        for chunk in response:
            if chunk.text:
                yield chunk.text
    else:
        response = await asyncio.to_thread(_model.generate_content, prompt)
        yield response.text


#  BONUS: Auth Server Interceptor

class AuthInterceptor(grpc.aio.ServerInterceptor):
    """
    Validates the 'Authorization: Bearer <key>' metadata on every call.
    Rejects with UNAUTHENTICATED if missing or wrong – never reaches service logic.
    """

    def __init__(self, valid_key: str):
        self._valid_key = valid_key

    async def intercept_service(self, continuation, handler_call_details):
        metadata = dict(handler_call_details.invocation_metadata)
        auth_header = metadata.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return self._abort(grpc.StatusCode.UNAUTHENTICATED, "Missing Bearer token")
        token = auth_header[len("Bearer "):]
        if token != self._valid_key:
            return self._abort(grpc.StatusCode.UNAUTHENTICATED, "Invalid API key")
        return await continuation(handler_call_details)

    @staticmethod
    def _abort(code, detail):
        async def handler(request, context):
            await context.abort(code, detail)
        return grpc.unary_unary_rpc_method_handler(handler)


# Service Implementation
class AIInferenceServicer(pb2_grpc.AIInferenceServicer):

    # Task 2: Unary – Sentiment Analysis
    async def AnalyzeSentiment(self, request: pb2.SentimentRequest, context: grpc.aio.ServicerContext):
        log.info("AnalyzeSentiment called | text_len=%d", len(request.text))



        prompt = f"""Analyze the sentiment of the following text.
Respond ONLY with valid JSON (no markdown) in this exact schema:
{{"label": "POSITIVE"|"NEGATIVE"|"NEUTRAL", "confidence": <0.0-1.0>, "reasoning": "<one sentence>"}}

Text: {request.text}"""

        try:
            raw = await asyncio.to_thread(_model.generate_content, prompt) if _model else None
            if raw is None:
                text = '{"label":"NEUTRAL","confidence":0.5,"reasoning":"Stub mode"}'
            else:
                text = raw.text.strip()
                # strip accidental markdown fences
                text = re.sub(r"```(?:json)?|```", "", text).strip()
            data = json.loads(text)
            return pb2.SentimentResponse(
                label=data.get("label", "NEUTRAL"),
                confidence=float(data.get("confidence", 0.5)),
                reasoning=data.get("reasoning", ""),
            )
        except Exception as exc:
            log.exception("AnalyzeSentiment error: %s", exc)
            await context.abort(grpc.StatusCode.INTERNAL, str(exc))

    # Task 3: Server-Streaming – Text Generation
    async def GenerateText(self, request: pb2.GenerationRequest, context: grpc.aio.ServicerContext):
        log.info("GenerateText called | prompt_len=%d", len(request.prompt))

        if _model is None:
            stub = f"[STUB] This is the generated response for: {request.prompt[:60]}"
            for word in stub.split():
                yield pb2.GenerationChunk(token=word + " ")
                await asyncio.sleep(0.05)
            return

        try:
            response = await asyncio.to_thread(
                _model.generate_content, request.prompt, stream=True
            )
            for chunk in response:
                if context.cancelled():
                    break
                if chunk.text:
                    yield pb2.GenerationChunk(token=chunk.text)
        except Exception as exc:
            log.exception("GenerateText error: %s", exc)
            await context.abort(grpc.StatusCode.INTERNAL, str(exc))

    # Task 4: Client-Streaming – Batch Summarization
    async def SummarizeDocument(self, request_iterator, context: grpc.aio.ServicerContext):
        log.info("SummarizeDocument called – receiving chunks…")
        chunks = []
        async for chunk in request_iterator:
            chunks.append(chunk.content)
            log.debug("  chunk %d received (%d chars)", chunk.chunk_index, len(chunk.content))

        full_text = "\n\n".join(chunks)
        log.info("All %d chunk(s) received, total %d chars", len(chunks), len(full_text))

        prompt = f"""Summarize the following text concisely in 3-5 sentences.

Text:
{full_text}"""

        try:
            if _model is None:
                summary = f"[STUB] Summary of {len(chunks)} chunk(s) totalling {len(full_text)} characters."
            else:
                raw = await asyncio.to_thread(_model.generate_content, prompt)
                summary = raw.text.strip()

            return pb2.SummaryResponse(summary=summary, chunks_received=len(chunks))
        except Exception as exc:
            log.exception("SummarizeDocument error: %s", exc)
            await context.abort(grpc.StatusCode.INTERNAL, str(exc))

    # Task 5: Bidirectional-Streaming – Live Chat
    async def LiveChat(self, request_iterator, context: grpc.aio.ServicerContext):
        log.info("LiveChat session opened")
        history = []   # list of {"role": ..., "parts": [...]}

        async for msg in request_iterator:
            if context.cancelled():
                break
            log.info("LiveChat message | turn=%s role=%s len=%d",
                     msg.turn_id, msg.role, len(msg.content))

            history.append({"role": "user", "parts": [msg.content]})

            if _model is None:
                reply_text = f"[STUB] Echo: {msg.content[:80]}"
                yield pb2.ChatMessage(role="assistant", content=reply_text, turn_id=msg.turn_id)
                continue

            try:
                chat = _model.start_chat(history=history[:-1])
                response = await asyncio.to_thread(
                    chat.send_message, msg.content, stream=True
                )
                accumulated = []
                for chunk in response:
                    if context.cancelled():
                        break
                    if chunk.text:
                        accumulated.append(chunk.text)
                        yield pb2.ChatMessage(
                            role="assistant",
                            content=chunk.text,
                            turn_id=msg.turn_id,
                        )
                history.append({"role": "model", "parts": ["".join(accumulated)]})
            except Exception as exc:
                log.exception("LiveChat error: %s", exc)
                yield pb2.ChatMessage(
                    role="assistant",
                    content=f"[ERROR] {exc}",
                    turn_id=msg.turn_id,
                )

        log.info("LiveChat session closed")



# Server Bootstrap
async def serve():
    interceptors = [AuthInterceptor(API_SECRET_KEY)]
    server = aio.server(interceptors=interceptors)
    pb2_grpc.add_AIInferenceServicer_to_server(AIInferenceServicer(), server)
    listen_addr = f"0.0.0.0:{PORT}"
    server.add_insecure_port(listen_addr)
    log.info("gRPC server listening on %s", listen_addr)
    await server.start()
    await server.wait_for_termination()


if __name__ == "__main__":
    asyncio.run(serve())
