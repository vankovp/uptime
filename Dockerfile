FROM python:3.11-slim
RUN rm /etc/localtime && ln -s /usr/share/zoneinfo/Europe/Moscow /etc/localtime
WORKDIR /usr/src/app
VOLUME /var/data
ADD requirements.txt /usr/src/app/
RUN pip install -r requirements.txt
ADD src /usr/src/app/
WORKDIR /usr/src/app
