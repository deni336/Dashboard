//go:generate rice embed-go
package storage

import (
	"fmt"
	"io"
	"log"
	"net/http"
	"os"

	rice "github.com/GeertJohan/go.rice"
	"github.com/fatih/color"
)

func HostUploadServer(addr string) {
	wrkDir, e := os.Getwd()
	if e != nil {
		fmt.Println(e)
	}
	wrkDir += "\\internal\\storage\\data"

	s := &http.Server{
		Addr:    addr,
		Handler: handleFormPost(),
	}

	fmt.Println("[success!] file upload server started on ", color.CyanString(addr))
	fmt.Println("Saving files to ", color.CyanString(wrkDir))

	log.Fatal(s.ListenAndServe())
}

func handleFormPost() (m *http.ServeMux) {
	mux := http.NewServeMux()
	// Serve static files with rice for portability
	staticFiles := rice.MustFindBox("./file_transfer_frontend").HTTPBox()

	mux.Handle("/", http.FileServer(staticFiles))

	mux.HandleFunc("/send", func(rw http.ResponseWriter, r *http.Request) {

		defer r.Body.Close()

		fileName := r.Header.Get("X-File-Name")
		if fileName == "" {
			log.Printf(color.RedString("File name not provided"))
			rw.WriteHeader(http.StatusBadRequest)
			return
		}

		outFile, err := os.Create(fileName)
		defer outFile.Close()
		if err != nil {
			log.Printf(color.RedString("Failed to create file: %v"), err)
			rw.WriteHeader(http.StatusInternalServerError)
			return
		}

		bar := bars.AddBar(int(r.ContentLength))
		progWriter := &ProgressWriter{
			Length:       r.ContentLength,
			FileName:     fileName,
			BytesWritten: 0,
			Bar:          bar,
			Writer:       outFile,
		}
		bar.AppendFunc(progWriter.Append())
		bar.PrependFunc(progWriter.Prepend())

		_, e := io.Copy(progWriter, r.Body)
		if e != nil {
			log.Printf(color.RedString("Failed to copy file: %v"), e)
			rw.WriteHeader(http.StatusInternalServerError)
			return
		}
	})

	return mux
}
