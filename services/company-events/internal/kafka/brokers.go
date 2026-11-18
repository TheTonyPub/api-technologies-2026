package kafka

import (
	"os"
	"strings"

	"github.com/twmb/franz-go/pkg/kgo"
)

func SeedBrokers() kgo.Opt {
	addresses := strings.FieldsFunc(os.Getenv("KAFKA_BROKERS"), func(r rune) bool {
		return r == ',' || r == ' '
	})
	if len(addresses) == 0 {
		addresses = []string{"localhost:29092"}
	}
	return kgo.SeedBrokers(addresses...)
}
