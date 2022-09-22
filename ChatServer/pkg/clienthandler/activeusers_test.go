package clienthandler

import (
	"testing"
)

func TestAddingActiveUsers(t *testing.T) {
	result := InitializeActiveUserList()

	result.Add("Skeebop")
	if !result.Search("Skeebop") {
		t.Error("failed adding to active users")
	}
}

func TestSearchingActiveUsers(t *testing.T) {
	result := InitializeActiveUserList()

	result.Add("Tim")
	if !result.Search("Skeebop") {
		return
	} else {
		t.Error("failed adding to active users")
	}
}

func TestDeletingActiveUsers(t *testing.T) {
	result := InitializeActiveUserList()
	key := "Cowboys"
	result.Add(key)
	if !result.Search(key) {
		t.Error("failed adding to active users")
	}

	result.Delete(key)

	if result.Search(key) {
		t.Error("failed to remove active users")
	}
}
