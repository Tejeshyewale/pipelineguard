FROM python:3.10-slim
WORKDIR /app
COPY requirements.txt requirements-dev.txt ./
RUN pip install -r requirements.txt -r requirements-dev.txt
RUN pip install websockets colorama
COPY . .
ENV PYTHONPATH=/app
CMD ["python", "examples/run_demo.py"]
