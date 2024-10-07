package messagegen

import (
	"math/rand"
	"time"
)

// List of random messages to send
var messages = []string{
	"Hello, how are you?",
	"What's your favorite programming language?",
	"Do you have any hobbies?",
	"Let's talk about Go!",
	"Have you tried gRPC?",
	"How's the weather today?",
	"Did you watch the latest movie?",
	"Are you interested in AI?",
	"What's your plan for the weekend?",
	"Let's catch up sometime!",
}

// MessageGenerator generates a random message at intervals
type MessageGenerator struct {
	interval time.Duration
	stop     chan bool
}

// NewMessageGenerator creates a new instance of MessageGenerator with a specified interval
func NewMessageGenerator(interval time.Duration) *MessageGenerator {
	return &MessageGenerator{
		interval: interval,
		stop:     make(chan bool),
	}
}

// Start begins generating messages at the defined interval
func (mg *MessageGenerator) Start(onMessage func(string)) {
	go func() {
		for {
			select {
			case <-mg.stop:
				return
			default:
				// Generate a random message from the list
				message := messages[rand.Intn(len(messages))]
				onMessage(message)

				// Wait for the next interval before generating another message
				time.Sleep(mg.interval)
			}
		}
	}()
}

// Stop stops the message generation
func (mg *MessageGenerator) Stop() {
	mg.stop <- true
}

// GenerateMessage generates a random message
func GenerateMessage() string {
	return messages[rand.Intn(len(messages))]
}
