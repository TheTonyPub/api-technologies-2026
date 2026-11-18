package main

import (
	"context"
	"fmt"
	"log"
	"os"
	"time"

	"github.com/TheTonyPub/api-technologies-2026/services/company-events/internal/kafka"
	"github.com/twmb/franz-go/pkg/kgo"
)

func main() {
	if err := run(); err != nil {
		log.Fatal(err)
	}
}

func run() error {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	session, err := kgo.NewGroupTransactSession(
		kafka.SeedBrokers(),
		kgo.ConsumeTopics("company.changes"),
		kgo.ConsumerGroup("company-audit-dev"),
		kgo.ConsumeResetOffset(kgo.NewOffset().AtStart()),
		kgo.DisableAutoCommit(),
		kgo.RequireStableFetchOffsets(),
		kgo.FetchIsolationLevel(kgo.ReadCommitted()),
		kgo.TransactionalID("company-audit-dev-1"),
	)
	if err != nil {
		return fmt.Errorf("create Kafka transaction session: %w", err)
	}
	defer session.Close()

	if err := session.Client().Ping(ctx); err != nil {
		return fmt.Errorf("connect to Kafka: %w", err)
	}

	log.Print("processor: Kafka connection OK")

	fetches := session.PollRecords(ctx, 1)
	if err := fetches.Err(); err != nil {
		return fmt.Errorf("read from Kafka: %w", err)
	}
	records := fetches.Records()
	if len(records) == 0 {
		return fmt.Errorf("no records received")
	}
	input := records[0]

	if err := session.Begin(); err != nil {
		return fmt.Errorf("begin transaction: %w", err)
	}

	output := &kgo.Record{
		Topic: "company.audit",
		Key:   input.Key,
		Value: input.Value,
	}
	if err := session.ProduceSync(ctx, output).FirstErr(); err != nil {
		abortCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		if _, abortErr := session.End(abortCtx, kgo.TryAbort); abortErr != nil {
			return fmt.Errorf("publish audit record: %w; abort transaction: %v", err, abortErr)
		}
		return fmt.Errorf("publish audit record: %w", err)
	}

	if os.Getenv("KAFKA_DEMO_ABORT") == "1" {
		if _, err := session.End(ctx, kgo.TryAbort); err != nil {
			return fmt.Errorf("abort demo transaction: %w", err)
		}
		log.Printf("aborted transaction for input offset=%d key=%s", input.Offset, input.Key)
		return nil
	}

	committed, err := session.End(ctx, kgo.TryCommit)
	if err != nil {
		return fmt.Errorf("end transaction: %w", err)
	}
	if !committed {
		return fmt.Errorf("Kafka aborted the transaction")
	}

	log.Printf("committed input offset=%d and published key=%s", input.Offset, input.Key)
	return nil
}
