FROM python:3.12

RUN mkdir /app
WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY iss_tracker.py /app/iss_tracker.py 
COPY test_iss_tracker.py /app/test_iss_tracker.py

ENV FLASK_APP=iss_tracker.py

EXPOSE 5000

ENTRYPOINT ["flask"]
CMD ["run", "--host=0.0.0.0", "--port=5000"]

