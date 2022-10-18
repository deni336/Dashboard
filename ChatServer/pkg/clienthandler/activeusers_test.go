package clienthandler

import (
	"fmt"
	"testing"
)

func TestAddingActiveUsers(t *testing.T) {
	result := InitializeActiveUserList()
	user := &User{
		Name:        "Skeebop",
		Address:     "192.168.45.1",
		Connection:  nil,
		IsConnected: true,
	}
	user2 := &User{
		Name:        "Skeebop",
		Address:     "192.168.45.1",
		Connection:  nil,
		IsConnected: true,
	}

	user3 := &User{
		Name:        "Skeebop",
		Address:     "192.168.45.1",
		Connection:  nil,
		IsConnected: true,
	}
	result.Add(user.Name, user)
	result.Add(user2.Name, user2)
	result.Add(user3.Name, user2)
	fmt.Println(result.userLoad)
	if !result.Search("Skeebop") {
		t.Error("failed adding to active users")
	}
}

func TestSearchingActiveUsers(t *testing.T) {
	result := InitializeActiveUserList()

	user := &User{
		Name:        "Tim",
		Address:     "192.168.45.1",
		Connection:  nil,
		IsConnected: true,
	}
	result.Add(user.Name, user)
	if !result.Search("Skeebop") {
		return
	} else {
		t.Error("failed adding to active users")
	}
}

func TestDeletingActiveUsers(t *testing.T) {
	result := InitializeActiveUserList()

	user := &User{
		Name:        "Cowboys",
		Address:     "192.168.45.1",
		Connection:  nil,
		IsConnected: true,
	}

	result.Add(user.Name, user)
	if !result.Search(user.Name) {
		t.Error("failed adding to active users")
	}

	result.Delete(user.Name)

	if result.Search(user.Name) {
		t.Error("failed to remove active users")
	}
}
