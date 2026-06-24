> **Fixture status:** Tiers 1–5 implemented. No planned fixture work remains in
> `capabilities.yaml`.

## Feature: Task list (Tier 1)

### Acceptance Criteria

- Tasks page loads at http://localhost:8080/tasks/ with page title "Sample App - Tasks"
- User can open the Tasks page and see the task list
- User can click "New Task", fill title and description, and save
- New task appears in the list with correct title
- API returns 200 on GET /api/tasks with a JSON array of tasks
- API returns 201 on POST /api/tasks with JSON body `{"title": "<title>", "description": "<optional>"}`

## Feature: Task management (Tier 2)

### Acceptance Criteria

- User can click "Mark Done" on a task and see a Done badge with strikethrough title
- User can click "Mark Active" to clear the done state
- User can click "Delete", confirm with "Confirm Delete" in the modal, and the task is removed from the list
- User can click "Cancel" or press Escape to dismiss the delete modal without deleting
- User can click "Load Demo Tasks" to seed 15 tasks and scroll the task list
- API returns 200 on PATCH /api/tasks/{id} with JSON body `{"completed": true}` or `{"completed": false}`
- API returns 204 on DELETE /api/tasks/{id}

## Feature: Advanced interactions (Tier 3)

### Acceptance Criteria

- Settings page loads at http://localhost:8080/settings/ with page title "Sample App - Settings"
- User can choose Light or Dark theme and click "Save Settings" to see "Settings saved."
- User can choose a default sort order (Newest first, Oldest first, Title A-Z) on Settings
- Tasks page search box filters the visible list as the user types
- User can click "Import Tasks", paste titles (one per line), click Next, review preview, and Confirm Import
- Imported tasks appear in the task list via POST /api/tasks

## Feature: Task detail (Tier 4)

### Acceptance Criteria

- User can click a task title on the Tasks page to open http://localhost:8080/tasks/{id}
- Task detail page shows page title "Sample App - Task Detail" with full title and description
- API returns 200 on GET /api/tasks/{id} with the matching task JSON

## Feature: Home dashboard (Tier 5)

### Acceptance Criteria

- Home page at http://localhost:8080/ shows a Task overview with total, active, and done counts
- Recent tasks on the home page link to task detail pages
- Dashboard counts match GET /api/tasks results
