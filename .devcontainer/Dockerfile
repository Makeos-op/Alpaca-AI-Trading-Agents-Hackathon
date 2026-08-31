FROM golang:1.27.0-alpine3.24 AS builder
RUN go install github.com/alpacahq/cli/cmd/alpaca@v0.0.13

# Instalar image de python (3.12.14)
FROM python:3.12.14-bookworm
WORKDIR /tmp-requirements
COPY --from=builder /go/bin/alpaca /usr/bin/alpaca
RUN pip install alpaca-py,python-dotenv

