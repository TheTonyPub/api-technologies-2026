FROM golang:1.24-alpine AS build
WORKDIR /src
COPY services/company-events/go.mod services/company-events/go.sum ./
RUN go mod download
COPY services/company-events/cmd ./cmd
COPY services/company-events/internal ./internal
RUN CGO_ENABLED=0 go build -trimpath -o /publisher ./cmd/publisher

FROM scratch
COPY --from=build /publisher /publisher
USER 65532:65532
ENTRYPOINT ["/publisher"]
