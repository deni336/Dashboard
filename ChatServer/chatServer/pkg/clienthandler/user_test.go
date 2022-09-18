package clienthandler

import (
	"testing"
)

func TestUser(t *testing.T) {
	u := &User{
		Name:        "Gerald",
		Connection:  nil,
		Address:     "123.123.123.255",
		IsConnected: true,
		WorkingDir:  "C:/",
	}

	ch := make(chan string)

	u.ClientWriter(ch)

	ch <- "Testing, test"
}
