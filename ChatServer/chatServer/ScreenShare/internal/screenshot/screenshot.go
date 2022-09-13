package screenshot

import (
	"chat/ScreenShare/internal/win64"
	"image"
)

// CaptureDisplay captures whole region of displayIndex'th display.
func CaptureDisplay(displayIndex int) (*image.RGBA, error) {
	rect := win64.GetDisplayBounds(displayIndex)
	return CaptureRect(rect)
}

// CaptureRect captures specified region of desktop.
func CaptureRect(rect image.Rectangle) (*image.RGBA, error) {
	return win64.Capture(rect.Min.X, rect.Min.Y, rect.Dx(), rect.Dy())
}
