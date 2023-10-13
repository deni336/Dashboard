package stdlog

import "log"

type LoggerAdapter struct {
}

func (l *LoggerAdapter) Infof(msg string, args ...interface{}) {
	log.Printf(msg, args...)
}

func (l *LoggerAdapter) Warningf(msg string, args ...interface{}) {
	log.Printf("[WARNING] "+msg, args...)
}

func (l *LoggerAdapter) Errorf(msg string, args ...interface{}) {
	log.Printf("[ERROR] "+msg, args...)
}

func (l *LoggerAdapter) Debugf(msg string, args ...interface{}) {
	log.Printf("[DEBUG] "+msg, args...)
}
