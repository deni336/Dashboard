package clienthandler

import "fmt"

type ActiveUsers struct {
	userLoad []*UserList
}

type UserList struct {
	head *UserNode
}

type UserNode struct {
	key  string
	user *User
	next *UserNode
}

func (au *ActiveUsers) Add(key string, user *User) {
	index := au.hash(key)

	if len(au.userLoad) <= 0 {
		au.userLoad = make([]*UserList, 0)
		au.userLoad = append(au.userLoad,
			&UserList{
				head: &UserNode{
					key:  key,
					user: user,
				},
			},
		)
		return
	}

	au.userLoad[index].add(key, user)
}

func (au *ActiveUsers) Search(key string) bool {
	index := au.hash(key)
	return au.userLoad[index].search(key)
}

func (au *ActiveUsers) Delete(key string) {
	index := au.hash(key)
	au.userLoad[index].delete(key)
}

func (au *ActiveUsers) ListUsers() map[string]*User {
	return au.list()
}

func (au *ActiveUsers) hash(key string) int {
	sum := 0
	for _, v := range key {
		sum += int(v)
	}

	if len(au.userLoad) <= 0 {
		return 0
	}

	return sum % len(au.userLoad)
}

func (ul *UserList) add(key string, user *User) {
	if !ul.search(key) {
		u := &UserNode{
			key:  key,
			user: user,
		}

		if ul.head == nil {
			ul.head = u
			return
		}

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

func (au *ActiveUsers) list() map[string]*User {
	user := make(map[string]*User)

	for _, v := range au.userLoad {

		for v.head != nil {
			user[v.head.key] = v.head.user
			v.head = v.head.next
		}

	}
	return user
}

func InitializeActiveUserList() *ActiveUsers {
	result := &ActiveUsers{}

	for i := range result.userLoad {
		result.userLoad[i] = &UserList{}
	}
	return result
}
