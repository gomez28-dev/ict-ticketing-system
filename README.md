# ICT Ticketing System — Setup Walkthrough for Collaborators

A step-by-step guide to download the project from GitHub and get it running locally in PyCharm.

---

## Prerequisites

Before you begin, make sure you have the following installed:

| Software | Version | Download Link |
|----------|---------|---------------|
| **Python** | 3.12 or higher | [python.org/downloads](https://www.python.org/downloads/) |
| **Git** | Latest | [git-scm.com/downloads](https://git-scm.com/downloads/) |
| **PyCharm** | Community or Professional | [jetbrains.com/pycharm](https://www.jetbrains.com/pycharm/download/) |

> **⚠️ IMPORTANT:** When installing Python on Windows, **check the "Add Python to PATH"** option during installation. This is critical for the commands below to work.

---

## Step 1: Download the Source Code from GitHub

### Option A — Clone via Git (Recommended)

1. Open a terminal (Command Prompt or PowerShell).
2. Navigate to the folder where you want to store the project:
   ```
   cd C:\Users\YourUsername\PycharmProjects
   ```
3. Clone the repository:
   ```
   git clone https://github.com/gomez28-dev/ict-ticketing-system.git
   ```
4. This will create a folder called `ict-ticketing-system` with all the project files.

### Option B — Download as ZIP

1. Go to **[https://github.com/gomez28-dev/ict-ticketing-system](https://github.com/gomez28-dev/ict-ticketing-system)**.
2. Click the green **`<> Code`** button.
3. Select **Download ZIP**.
4. Extract the ZIP to `C:\Users\YourUsername\PycharmProjects\`.
5. Rename the extracted folder from `ict-ticketing-system-main` to `ict-ticketing-system` (optional, for cleanliness).

---

## Step 2: Open the Project in PyCharm

1. Open **PyCharm**.
2. On the Welcome screen, click **Open**.
3. Browse to `C:\Users\YourUsername\PycharmProjects\ict-ticketing-system` and click **OK**.
4. If prompted to "Trust this project?", click **Trust Project**.

---

## Step 3: Create a Virtual Environment

PyCharm may prompt you to create a virtual environment automatically. If it does, accept the defaults. Otherwise, create one manually:

### Using PyCharm UI

1. Go to **File → Settings → Project: ict-ticketing-system → Python Interpreter**.
2. Click the **gear icon ⚙** → **Add Interpreter** → **Add Local Interpreter**.
3. Select **Virtualenv Environment** → **New**.
4. Make sure the **Base Interpreter** points to your Python 3.12+ installation.
5. Click **OK**.

### Using the Terminal (Alternative)

1. Open PyCharm's built-in terminal: **View → Tool Windows → Terminal**.
2. Run:
   ```
   python -m venv .venv
   ```
3. Activate the virtual environment:
   ```
   .venv\Scripts\activate
   ```

> **📝 NOTE:** You should see `(.venv)` at the beginning of your terminal prompt once activated. All following commands should be run inside this activated environment.

---

## Step 4: Install Dependencies

In the PyCharm terminal (with the virtual environment activated), run:

```
pip install -r requirements.txt
```

This will install the following key packages:

| Package | Purpose |
|---------|---------|
| Django 6.0.2 | Web framework |
| pandas 3.0.1 | Data handling (school imports) |
| scikit-learn 1.8.0 | ML-based ticket classification |

---

## Step 5: Set Up the Database

Run Django migrations to create the database tables:

```
python manage.py migrate
```

This creates a local `db.sqlite3` file in the project root with all the required tables.

---

## Step 6: Import School Data

The project includes a `schools.xlsx` file with school records. Import them into the database:

```
python manage.py import_schools
```

> **📝 NOTE:** This command reads `schools.xlsx` from the project root and populates the school records used for the login and ticketing system.

---

## Step 7: Create a Superuser (Admin Account)

To access the admin dashboard, create a superuser account:

```
python manage.py createsuperuser
```

You will be prompted to enter:
- **Username** — choose anything (e.g., `admin`)
- **Email** — can be left blank (press Enter)
- **Password** — choose a password (won't be visible as you type)

---

## Step 8: Run the Development Server

Start the Django development server:

```
python manage.py runserver
```

Once running, open your browser and go to:

| Page | URL |
|------|-----|
| **School Login** | [http://127.0.0.1:8000/](http://127.0.0.1:8000/) |
| **Admin Login** | [http://127.0.0.1:8000/admin-login/](http://127.0.0.1:8000/admin-login/) |

> **💡 TIP:** To stop the server, press `Ctrl + C` in the terminal.

---

## Step 9: Configure the Run Configuration in PyCharm (Optional)

To run the server with a single click instead of typing the command each time:

1. Go to **Run → Edit Configurations**.
2. Click **+** → **Django Server** (if available) or **Python**.
3. Configure:
   - **Script path**: Select `manage.py` from the project root.
   - **Parameters**: `runserver`
   - **Python interpreter**: Select the `.venv` interpreter you created.
4. Click **OK**.
5. Now you can start the server by clicking the green **▶ Run** button.

---

## Quick Reference — Full Command Sequence

For those who prefer to set up everything at once in the terminal:

```bash
# 1. Clone the repo
git clone https://github.com/gomez28-dev/ict-ticketing-system.git
cd ict-ticketing-system

# 2. Create & activate virtual environment
python -m venv .venv
.venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up database
python manage.py migrate

# 5. Import school data
python manage.py import_schools

# 6. Create admin account
python manage.py createsuperuser

# 7. Run the server
python manage.py runserver
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `python` is not recognized | Re-install Python and check **"Add to PATH"** during setup |
| `pip` is not recognized | Run `python -m pip install -r requirements.txt` instead |
| Port 8000 already in use | Run `python manage.py runserver 8080` to use a different port |
| Module not found errors | Make sure the virtual environment is activated (`(.venv)` in prompt) |
| `import_schools` fails | Ensure `schools.xlsx` is in the project root directory |
