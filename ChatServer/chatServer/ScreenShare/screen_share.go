package chat

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

	screenshot "chat/ScreenShare/internal/screenshot"
)

type Todo struct {
	Title string
	Done  bool
}

type TodoPageData struct {
	PageTitle string
	Todos     []Todo
}

var interrupt = make(chan bool, 1)
var bytesToSend = make([]byte, 0) // current image going to user

func StartScreenShareServer() {
	addr := "192.168.45.10:7070"
	//root := "./temp"

	//var err error

	// root, err = filepath.Abs(root)
	// if err != nil {
	// 	fmt.Println(err)
	// }

	currentTime := time.Now()
	fmt.Println("Share Screen server started...", currentTime.Format("Mon 02 2006 03:04pm"))
	//log.Printf("serving %s as %s on %s", root, prefix, addr)
	//http.Handle(prefix, http.StripPrefix(prefix, http.FileServer(http.Dir(root))))

	// tmpl := template.Must(template.ParseFiles(root + "\\layout.html"))
	// http.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
	// 	data := TodoPageData{
	// 		PageTitle: "My TODO list",
	// 		Todos: []Todo{
	// 			{Title: "Task 1", Done: false},
	// 			{Title: "Task 2", Done: true},
	// 			{Title: "Task 3", Done: true},
	// 		},
	// 	}
	// 	tmpl.Execute(w, data)
	// })

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

func takeScreenShot(w http.ResponseWriter, r *http.Request) {
	fmt.Fprintf(w, "Sharing Screen Started")
	ticker := time.NewTicker(500 * time.Millisecond)
	defer ticker.Stop()
	buf := new(bytes.Buffer)

	for {
		select {
		case <-ticker.C:
			img, err := screenshot.CaptureDisplay(0)
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

func fetchScreenShot(w http.ResponseWriter, r *http.Request) {
	filename := ""
	body, err := ioutil.ReadFile(filename)
	if err != nil {
		fmt.Fprint(w, err)
	}
	fmt.Fprintf(w, string(body))
}

func stopSharing(w http.ResponseWriter, r *http.Request) {
	interrupt <- true
	fmt.Fprintf(w, "Share Screen has been stopped")
}

// this will send the current
func fetchPNG(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "image/png")
	w.Header().Set("Content-Length", strconv.Itoa(len(bytesToSend)))
	w.Header().Set("Cache-Control", "no-store, no-cache, must-revalidate, post-check=0, pre-check=0") // dont want to cache the screenshot image here
	if _, err := w.Write(bytesToSend); err != nil {
		log.Println("Unable to write image")
	}
	log.Println("PNG sent to user")
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
