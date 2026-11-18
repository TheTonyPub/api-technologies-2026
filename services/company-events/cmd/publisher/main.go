package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"log"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/TheTonyPub/api-technologies-2026/services/company-events/internal/kafka"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/twmb/franz-go/pkg/kgo"
)

const (
	changeTopic     = "company.changes"
	deliveryTimeout = 10 * time.Second
)

type companyChanged struct {
	EventID    string    `json:"event_id"`
	VersionID  int64     `json:"version_id"`
	INN        string    `json:"inn"`
	OccurredAt time.Time `json:"occurred_at"`
	Type       string    `json:"type"`
}

func main() {
	once := flag.Bool("once", false, "publish at most one pending event and exit")
	flag.Parse()

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if err := run(ctx, *once); err != nil && !errors.Is(err, context.Canceled) {
		log.Fatal(err)
	}
}

func run(ctx context.Context, once bool) error {
	dsn := os.Getenv("DATABASE_URL")
	if dsn == "" {
		return errors.New("DATABASE_URL is required")
	}
	db, err := pgxpool.New(ctx, dsn)
	if err != nil {
		return errors.New("could not configure PostgreSQL connection from DATABASE_URL")
	}
	defer db.Close()
	connectCtx, cancel := context.WithTimeout(ctx, 10*time.Second)
	err = db.Ping(connectCtx)
	cancel()
	if err != nil {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		return errors.New("could not connect to PostgreSQL; check DATABASE_URL and server availability")
	}

	client, err := kgo.NewClient(
		kafka.SeedBrokers(),
		kgo.RequiredAcks(kgo.AllISRAcks()),
		kgo.RecordDeliveryTimeout(deliveryTimeout),
	)
	if err != nil {
		return fmt.Errorf("create Kafka client: %w", err)
	}
	defer client.Close()

	for ctx.Err() == nil {
		attemptCtx, cancel := context.WithTimeout(ctx, deliveryTimeout+5*time.Second)
		published, err := publishNext(attemptCtx, db, client)
		cancel()
		if once {
			if err == nil && !published {
				log.Print("publisher: no pending events")
			}
			return err
		}
		if err != nil && ctx.Err() == nil {
			log.Printf("publisher: will retry: %v", err)
		}
		if err == nil && published {
			continue
		}
		timer := time.NewTimer(time.Second)
		select {
		case <-ctx.Done():
			timer.Stop()
		case <-timer.C:
		}
	}
	return ctx.Err()
}

func publishNext(ctx context.Context, db *pgxpool.Pool, client *kgo.Client) (bool, error) {
	event := companyChanged{Type: "CompanyChanged"}
	published := false
	err := pgx.BeginFunc(ctx, db, func(tx pgx.Tx) error {
		// Keep the row locked until Kafka acknowledges it and PostgreSQL commits.
		err := tx.QueryRow(ctx, `
			SELECT event_id::text, version_id, inn, occurred_at
			FROM company_outbox
			WHERE published_at IS NULL
			ORDER BY version_id
			LIMIT 1
			FOR UPDATE
		`).Scan(&event.EventID, &event.VersionID, &event.INN, &event.OccurredAt)
		if errors.Is(err, pgx.ErrNoRows) {
			return nil
		}
		if err != nil {
			return fmt.Errorf("read pending outbox event: %w", err)
		}

		event.OccurredAt = event.OccurredAt.UTC()
		value, err := json.Marshal(event)
		if err != nil {
			return fmt.Errorf("encode event %s: %w", event.EventID, err)
		}
		record := &kgo.Record{Topic: changeTopic, Key: []byte(event.INN), Value: value}
		if err := client.ProduceSync(ctx, record).FirstErr(); err != nil {
			return fmt.Errorf("send event %s: %w", event.EventID, err)
		}
		if _, err := tx.Exec(ctx, `
			UPDATE company_outbox SET published_at = statement_timestamp() WHERE version_id = $1
		`, event.VersionID); err != nil {
			return fmt.Errorf("mark event %s published: %w", event.EventID, err)
		}
		published = true
		return nil
	})
	if err != nil {
		return false, fmt.Errorf("publish next outbox event: %w", err)
	}
	if published {
		log.Printf("published event_id=%s version_id=%d topic=%s", event.EventID, event.VersionID, changeTopic)
	}
	return published, nil
}
