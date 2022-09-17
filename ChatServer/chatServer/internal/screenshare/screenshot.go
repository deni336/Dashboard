package screenshare

import (
	"chat/pkg/utils"
	"image"
)

// CaptureDisplay captures whole region of displayIndex'th display.
func CaptureDisplay(displayIndex int) (*image.RGBA, error) {
	rect := utils.GetDisplayBounds(displayIndex)
	return CaptureRect(rect)
}

// CaptureRect captures specified region of desktop.
func CaptureRect(rect image.Rectangle) (*image.RGBA, error) {
	return utils.Capture(rect.Min.X, rect.Min.Y, rect.Dx(), rect.Dy())
}
