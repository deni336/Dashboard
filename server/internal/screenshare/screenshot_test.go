package screenshare

import (
	"chat/pkg/utils"
	"testing"
)

func TestCaptureRect(t *testing.T) {
	bounds := utils.GetDisplayBounds(0)

	_, err := CaptureRect(bounds)
	if err != nil {
		t.Error(err)
	}
}

func BenchmarkCaptureRect(t *testing.B) {
	bounds := utils.GetDisplayBounds(0)
	t.ResetTimer()
	for i := 0; i < t.N; i++ {
		_, err := CaptureRect(bounds)
		if err != nil {
			t.Error(err)
		}
	}
}
