package main

// import (
// 	pb "chat/pkg/grpc"
// 	"time"
// )

// type FakeActiveUsers struct {
// }

// func (c *FakeActiveUsers) FakeUserList() *pb.ActiveUsersList {
// 	return &pb.ActiveUsersList{
// 		Users: getUsers(),
// 	}
// }

// func getUsers() []*pb.User {
// 	ul := []*pb.User{
// 		{
// 			Name: "George",
// 			Message: &pb.MessageResponse{
// 				Message:   "Hello from George.",
// 				Timestamp: time.Now().Format("02-02-2009"),
// 			},
// 		},
// 		{
// 			Name: "Albert",
// 			Message: &pb.MessageResponse{
// 				Message:   "Albert says hello.",
// 				Timestamp: time.Now().Format("02-02-2009"),
// 			},
// 		},
// 		{
// 			Name: "Nathan",
// 			Message: &pb.MessageResponse{
// 				Message:   "Greetings from Nathan.",
// 				Timestamp: time.Now().Format("02-02-2009"),
// 			},
// 		},
// 	}
// 	return ul
// }
