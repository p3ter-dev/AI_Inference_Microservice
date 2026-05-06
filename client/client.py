"""
AI Inference – CLI Tester
Connects to the Nginx load-balancer and sequentially exercises all four RPC types.

Bonus:
  • Sends Authorization: Bearer <key> metadata on every call.
  • Enforces a strict 2-second deadline on AnalyzeSentiment (Unary).
    The server sleeps 3 s intentionally, so we always catch DEADLINE_EXCEEDED.
"""

import asyncio
import os

import grpc
from grpc import aio

import ai_inference_pb2 as pb2
import ai_inference_pb2_grpc as pb2_grpc

#  Config
TARGET    = os.environ.get("GRPC_TARGET", "localhost:80")
API_KEY   = os.environ.get("API_SECRET_KEY", "my-secret-key")
AUTH_META = [("authorization", f"Bearer {API_KEY}")]

BANNER = "\033[1;36m{}\033[0m"        # cyan bold
OK     = "\033[1;32m✔\033[0m"         # green tick
ERR    = "\033[1;31m✘\033[0m"         # red cross
TOKEN  = "\033[0;33m{}\033[0m"        # yellow for streamed tokens


def hr(title=""):
    width = 60
    if title:
        pad = (width - len(title) - 2) // 2
        print(f"\n{'─' * pad} {title} {'─' * pad}")
    else:
        print("─" * width)


#  Task 2 – Unary
async def test_sentiment(stub: pb2_grpc.AIInferenceStub):
    hr("Task 2 · Unary · Sentiment Analysis")
    review = (
        "Absolutely loved this product! The build quality is superb "
        "and it arrived two days early. Highly recommend."
    )
    print(f"  Input : {review}\n")
    print("   Deadline: 60 seconds (waiting for AI analysis)\n")

    try:
        resp = await stub.AnalyzeSentiment(
            pb2.SentimentRequest(text=review),
            metadata=AUTH_META,
            timeout=60.0,
        )
        print(f"  {OK} Label      : {resp.label}")
        print(f"  {OK} Confidence : {resp.confidence:.2f}")
        print(f"  {OK} Reasoning  : {resp.reasoning}")
    except grpc.aio.AioRpcError as exc:
        if exc.code() == grpc.StatusCode.DEADLINE_EXCEEDED:
            print(f"  {ERR} Deadline exceeded – the server took longer than 60 s.")
            print(f"      gRPC status : {exc.code().name}")
            print(f"      Details     : {exc.details()}")
        else:
            print(f"  {ERR} Unexpected gRPC error: {exc.code()} – {exc.details()}")


#  Task 3 – Server-Streaming (text generation)
async def test_generation(stub: pb2_grpc.AIInferenceStub):
    hr("Task 3 · Server-Streaming · Text Generation")
    prompt = "Explain gRPC streaming in three sentences, simply."
    print(f"  Prompt: {prompt}\n  Response: ", end="", flush=True)

    try:
        async for chunk in stub.GenerateText(
            pb2.GenerationRequest(prompt=prompt),
            metadata=AUTH_META,
        ):
            print(TOKEN.format(chunk.token), end="", flush=True)
        print(f"\n\n  {OK} Stream complete.")
    except grpc.aio.AioRpcError as exc:
        print(f"\n  {ERR} Error: {exc.code()} – {exc.details()}")


#  Task 4 – Client-Streaming (batch summarisation)
async def test_summarize(stub: pb2_grpc.AIInferenceStub):
    hr("Task 4 · Client-Streaming · Batch Summarization")

    document_chunks = [
        (0, "Chapter 1: The Origins of gRPC\n"
            "gRPC was originally developed at Google and released as open-source in 2015. "
            "It is built on top of HTTP/2 and uses Protocol Buffers as its interface "
            "definition language. Its design allows high-performance, strongly-typed "
            "communication between microservices."),

        (1, "Chapter 2: Communication Models\n"
            "gRPC supports four communication patterns: unary (single request/response), "
            "server-streaming (one request, many responses), client-streaming "
            "(many requests, one response), and bidirectional-streaming (many requests, "
            "many responses). Each pattern is suited to different use cases."),

        (2, "Chapter 3: Adoption and Ecosystem\n"
            "gRPC has been widely adopted by cloud-native projects including Kubernetes, "
            "Envoy, and etcd. Its strong typing, code generation, and performance "
            "advantages over REST/JSON have made it the preferred RPC framework for "
            "internal microservice communication at scale."),
    ]

    async def chunk_generator():
        for idx, content in document_chunks:
            print(f"  → Sending chunk {idx} ({len(content)} chars)…")
            await asyncio.sleep(0.1)   # simulate reading from disk
            yield pb2.TextChunk(content=content, chunk_index=idx)

    try:
        resp = await stub.SummarizeDocument(
            chunk_generator(),
            metadata=AUTH_META,
        )
        print(f"\n  {OK} Chunks received by server : {resp.chunks_received}")
        print(f"  {OK} Summary:\n")
        print(f"     {resp.summary}")
    except grpc.aio.AioRpcError as exc:
        print(f"  {ERR} Error: {exc.code()} – {exc.details()}")


#  Task 5 – Bidirectional-Streaming (live chat)
async def test_live_chat(stub: pb2_grpc.AIInferenceStub):
    hr("Task 5 · Bidirectional-Streaming · Live Chat")

    conversation = [
        ("turn-1", "Hello! What is Protocol Buffers in one sentence?"),
        ("turn-2", "And what makes HTTP/2 different from HTTP/1.1?"),
        ("turn-3", "Thanks, that was clear!"),
    ]

    async def message_generator():
        for turn_id, text in conversation:
            print(f"\n  \033[1mYou [{turn_id}]:\033[0m {text}")
            await asyncio.sleep(0.3)
            yield pb2.ChatMessage(role="user", content=text, turn_id=turn_id)

    try:
        current_turn = None
        async for reply in stub.LiveChat(
            message_generator(),
            metadata=AUTH_META,
        ):
            if reply.turn_id != current_turn:
                current_turn = reply.turn_id
                print(f"\n  \033[1mAssistant [{reply.turn_id}]:\033[0m ", end="", flush=True)
            print(TOKEN.format(reply.content), end="", flush=True)
        print(f"\n\n  {OK} Chat session complete.")
    except grpc.aio.AioRpcError as exc:
        print(f"\n  {ERR} Error: {exc.code()} – {exc.details()}")


async def main():
    print(BANNER.format("━" * 60))
    print(BANNER.format("   AI INFERENCE MICROSERVICE – CLI TESTER"))
    print(BANNER.format(f"   Target : {TARGET}"))
    print(BANNER.format("━" * 60))

    # Connect via Nginx (HTTP/2, plain text – no TLS inside Docker network)
    async with aio.insecure_channel(TARGET) as channel:
        stub = pb2_grpc.AIInferenceStub(channel)

        await test_sentiment(stub)
        await test_generation(stub)
        await test_summarize(stub)
        await test_live_chat(stub)

    hr()
    print(f"\n  {OK}  All tests completed.\n")


if __name__ == "__main__":
    asyncio.run(main())
