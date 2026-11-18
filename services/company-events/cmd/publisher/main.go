package main

import (
	"context"
	"errors"
	"fmt"
	"log"
	"os"
	"time"

	"github.com/TheTonyPub/api-technologies-2026/services/company-events/internal/kafka"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/twmb/franz-go/pkg/kgo"
)

func main() {
	if err := run(); err != nil {
		log.Fatal(err)
	}
}

func run() error {
	dsn := os.Getenv("DATABASE_URL")
	if dsn == "" {
		return errors.New("DATABASE_URL is required")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	db, err := pgxpool.New(ctx, dsn)
	if err != nil {
		return errors.New("could not configure PostgreSQL connection from DATABASE_URL")
	}
	defer db.Close()
	if err := db.Ping(ctx); err != nil {
		return errors.New("could not connect to PostgreSQL; check DATABASE_URL and server availability")
	}

	client, err := kgo.NewClient(kafka.SeedBrokers())
	if err != nil {
		return fmt.Errorf("create Kafka client: %w", err)
	}
	defer client.Close()
	if err := client.Ping(ctx); err != nil {
		return fmt.Errorf("connect to Kafka: %w", err)
	}

	log.Print("publisher: PostgreSQL and Kafka connections OK")
	return nil
}
