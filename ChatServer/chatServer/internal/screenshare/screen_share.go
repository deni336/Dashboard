package screenshare

import (
	"bytes"
	"fmt"
	"image/png"
	"io/ioutil"
	"log"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"syscall"
	"time"
)

var interrupt = make(chan bool, 1)
var bytesToSend = make([]byte, 0) // current image going to user

func InitScreenShareServer(addr string) {
	currentTime := time.Now()
	fmt.Println("[success!] screen share server started and listening on", addr, currentTime.Format("Mon 02 2006 03:04pm"))
	calls := `screen share server endpoints:
	- ip:port/start-sharing <- This shares your screen
	- ip:port/shared-screen <- This gets a snapshot of the shared screen
	- ip:port/stop-sharing <- This interrupts the sharing process and stops the stream.
	- ip:port/fetch-png <- This will display the screen being shared.
	`
	fmt.Println(calls)

	http.HandleFunc("/start-sharing", takeScreenShot)
	http.HandleFunc("/shared-screen", fetchScreenShot)
	http.HandleFunc("/stop-sharing", stopSharing)
	http.HandleFunc("/fetch-png", fetchPNG)

	mux := http.DefaultServeMux.ServeHTTP
	logger := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		log.Println(r.RemoteAddr + " " + r.Method + " " + r.URL.String())
		mux(w, r)
	})

	e := http.ListenAndServe(addr, logger)
	if e != nil {
		log.Fatalln(e)
	}

	gracefulTerminateSystem()
}

func fetchPNG(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "image/png")
	w.Header().Set("Content-Length", strconv.Itoa(len(bytesToSend)))
	w.Header().Set("Cache-Control", "no-store, no-cache, must-revalidate, post-check=0, pre-check=0") // dont want to cache the screenshot image here
	if _, err := w.Write(bytesToSend); err != nil {
		log.Println("Unable to write image")
	}
	log.Println("PNG sent to user")
}

func fetchScreenShot(w http.ResponseWriter, r *http.Request) {
	filename := ""
	body, err := ioutil.ReadFile(filename)
	if err != nil {
		fmt.Fprint(w, err)
	}
	fmt.Fprintf(w, string(body))
}

func gracefulTerminateSystem() {
	c := make(chan os.Signal, 2)
	signal.Notify(c, os.Interrupt, syscall.SIGTERM)

	go func() {
		<-c
		interrupt <- true
		fmt.Println("Ctrl+C was pressed in terminal")
		os.Exit(0)
	}()
}

func stopSharing(w http.ResponseWriter, r *http.Request) {
	interrupt <- true
	fmt.Fprintf(w, "Share Screen has been stopped")
}

func takeScreenShot(w http.ResponseWriter, r *http.Request) {
	fmt.Fprintf(w, "Sharing Screen Started")
	ticker := time.NewTicker(500 * time.Millisecond)
	defer ticker.Stop()
	buf := new(bytes.Buffer)

	for {
		select {
		case <-ticker.C:
			img, err := CaptureDisplay(0)
			if err != nil {
				panic(err)
			}

			png.Encode(buf, img)
			bytesToSend = buf.Bytes()
			buf.Reset()
		case <-interrupt:
			log.Println("Ending stream...")
			select {
			case <-time.After(time.Second):
			}
			return
		}
	}
}
