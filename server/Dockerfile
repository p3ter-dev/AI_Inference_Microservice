FROM python:3.11-slim

WORKDIR /app

# Install dependencies (grpcio-tools included for stub generation)
COPY server/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Generate protobuf stubs from the canonical proto source
COPY protos/ protos/
RUN python -m grpc_tools.protoc \
    -I protos \
    --python_out=. \
    --grpc_python_out=. \
    protos/ai_inference.proto

# Copy application code
COPY server/server.py server.py

EXPOSE 50051

CMD ["python", "server.py"]
