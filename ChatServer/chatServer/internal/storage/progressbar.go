package storage

import (
	"fmt"
	"io"
	"time"

	"github.com/gosuri/uiprogress"
)

var bars *uiprogress.Progress
var byteUnits = []string{"B", "KB", "MB", "GB", "TB", "PB"}

type ProgressWriter struct {
	Length       int64
	FileName     string
	BytesWritten int64
	Bar          *uiprogress.Bar
	io.Writer
}

func (w *ProgressWriter) Write(bytes []byte) (int, error) {
	bars.RefreshInterval = time.Millisecond * 300

	n, err := w.Writer.Write(bytes)
	w.BytesWritten += int64(n)
	w.Bar.Set(int(w.BytesWritten))

	if err == io.EOF {
		// Slow down, end of a progress bar.
		bars.RefreshInterval = time.Second * 10
	}

	return n, err
}

func (w *ProgressWriter) Prepend() func(*uiprogress.Bar) string {
	return func(bar *uiprogress.Bar) string {
		return w.FileName
	}
}

func (w *ProgressWriter) Append() func(*uiprogress.Bar) string {
	total := byteUnitStr(w.Length)

	return func(bar *uiprogress.Bar) string {
		completed := byteUnitStr(w.BytesWritten)
		return bar.CompletedPercentString() + " " + completed + "/" + total
	}
}

func byteUnitStr(n int64) string {
	var unit string
	size := float64(n)
	for i := 1; i < len(byteUnits); i++ {
		if size < 1000 {
			unit = byteUnits[i-1]
			break
		}

		size = size / 1000
	}

	return fmt.Sprintf("%.3g %s", size, unit)
}
