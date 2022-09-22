package clienthandler

import "fmt"

type ActiveUsers struct {
	userLoad [100]*UserList
}

type UserList struct {
	head *UserNode
}

type UserNode struct {
	key  string
	next *UserNode
}

func (au *ActiveUsers) Add(key string) {
	index := au.hash(key)
	au.userLoad[index].add(key)
}

func (au *ActiveUsers) Search(key string) bool {
	index := au.hash(key)
	return au.userLoad[index].search(key)
}

func (au *ActiveUsers) Delete(key string) {
	index := au.hash(key)
	au.userLoad[index].delete(key)
}

func (au *ActiveUsers) hash(key string) int {
	sum := 0
	for _, v := range key {
		sum += int(v)
	}

	return sum % len(au.userLoad)
}

func (ul *UserList) add(key string) {
	if !ul.search(key) {
		u := &UserNode{key: key}
		u.next = ul.head
		ul.head = u
	} else {
		fmt.Println("User already exist")
	}
}

func (ul *UserList) search(key string) bool {
	current := ul.head
	for current != nil {
		if current.key == key {
			return true
		}
		current = current.next
	}

	return false
}

func (ul *UserList) delete(key string) {
	if ul.head.key == key {
		ul.head = ul.head.next
		return
	}

	prev := ul.head
	for prev.next != nil {
		if prev.key == key {
			prev.next = prev.next.next
		}
		prev = prev.next
	}
}

func InitializeActiveUserList() *ActiveUsers {
	result := &ActiveUsers{}

	for i := range result.userLoad {
		result.userLoad[i] = &UserList{}
	}
	return result
}
