package clienthandler

import (
	"testing"
)

func TestClientListener(t *testing.T) {
	_, err := ClientListener("192.168.45.12:6969")
	if err != nil {
		t.Error(err)
	}
}
