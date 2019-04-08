FROM python:3.6

WORKDIR /app

ADD ./requirements.txt /app/requirements.txt
RUN pip install -r requirements.txt

ADD . /app

EXPOSE 5555

CMD gunicorn --workers 1 --bind 0.0.0.0:5555 -k eventlet app:app
