package utils

import (
	"image"
	"testing"
)

func TestCreateImage(t *testing.T) {
	rect := image.Rect(0, 0, 1920, 1080)
	_, err := CreateImage(rect)
	if err != nil {
		t.Error(err)
	}
}

func TestParse(t *testing.T) {
	buf := []byte("Hello World")
	s := ParseBuf(buf)
	if s == "" {
		t.Error("failed paring buffer")
	}
}

func TestReadBuf(t *testing.T) {
	// Setup connection for this test
}
