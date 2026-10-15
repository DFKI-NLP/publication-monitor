FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY monitor_publications.py contacts.py ./
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 STATE_FILE=/state/known_publication_ids.json
# Override the UID/GID if using a bind mount owned by another user.
RUN mkdir /state && chown 10001:10001 /state
USER 10001:10001
ENTRYPOINT ["python", "monitor_publications.py"]
