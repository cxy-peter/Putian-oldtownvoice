FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py engine.py store.py ./
COPY public ./public
RUN useradd --uid 10001 --create-home app && mkdir /data && chown app:app /data
USER app
ENV PYTHONUNBUFFERED=1 HOST=0.0.0.0 PORT=8080 DATA_DIR=/data
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,os; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8080')+'/healthz',timeout=4)"
CMD ["python", "app.py"]
