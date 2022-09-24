package utils

import (
	"bytes"
	"errors"
	"fmt"
	"image"
	"io"
	"log"
	"net"
	"strings"
)

func CreateImage(rect image.Rectangle) (img *image.RGBA, e error) {
	img = nil
	e = errors.New("cannot create image.RGBA")

	defer func() {
		err := recover()
		if err == nil {
			e = nil
		}
	}()
	// image.NewRGBA may panic if rect is too large.
	img = image.NewRGBA(rect)

	return img, e
}

func ParseBuf(cleanBuff []byte) (s string) {
	str := strings.Trim(string(cleanBuff), "\n")
	return str
}

func ReadBuf(conn net.Conn) (str string) {
	buffer := make([]byte, 1024)
	_, err := conn.Read(buffer)
	if err != nil && err != io.EOF {
		fmt.Println(err)
		log.Fatal(err)
	}

	str = ParseBuf(bytes.Trim(buffer, "\x00"))
	return str
}
