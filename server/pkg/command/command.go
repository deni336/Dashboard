package command

import (
	"dirtyRAT/pkg/c2"
	"fmt"
	"strconv"
)

type Command struct {
	Cmd       string
	Arguments []string
}

func NewCommand(req *c2.CommandRequest) *Command {
	return &Command{
		Cmd:       req.Command,
		Arguments: req.Arguments,
	}
}

type CommandFunc func(args ...string) string

type CommandDispatcher struct {
	dispatchTable map[string]CommandFunc
}

func NewCommandDispatcher() *CommandDispatcher {
	return &CommandDispatcher{
		dispatchTable: make(map[string]CommandFunc),
	}
}

func (d *CommandDispatcher) RegisterCommand(command string, function CommandFunc) {
	d.dispatchTable[command] = function
}

func (d *CommandDispatcher) ExecuteCommand(command string, args ...string) string {
	if function, exists := d.dispatchTable[command]; exists {
		return function(args...)
	}
	return fmt.Sprintf("Unknown command: %s", command)
}

func Greet(args ...string) string {
	if len(args) > 0 {
		return fmt.Sprintf("Hello, %s!", args[0])
	}
	return "Hello!"
}

func Add(args ...string) string {
	if len(args) >= 2 {
		x, _ := strconv.Atoi(args[0])
		y, _ := strconv.Atoi(args[1])
		return fmt.Sprintf("Result: %d", x+y)
	}
	return "Invalid input for add."
}
