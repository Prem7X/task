from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-change-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///taskmanager.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ─── Models ────────────────────────────────────────────────────────────────────

class Category(db.Model):
    __tablename__ = 'categories'
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(50), nullable=False, unique=True)
    color      = db.Column(db.String(7), default='#6366f1')
    tasks      = db.relationship('Task', backref='category', lazy=True, cascade='all, delete-orphan')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def task_count(self):
        return len(self.tasks)

    def __repr__(self):
        return f'<Category {self.name}>'


class Task(db.Model):
    __tablename__ = 'tasks'
    id          = db.Column(db.Integer, primary_key=True)
    title       = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default='')
    priority    = db.Column(db.String(10), default='medium')   # low | medium | high
    status      = db.Column(db.String(20), default='pending')  # pending | in_progress | done
    due_date    = db.Column(db.Date, nullable=True)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=True)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at  = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<Task {self.title}>'

    def is_overdue(self):
        if self.due_date and self.status != 'done':
            return self.due_date < datetime.utcnow().date()
        return False

    def is_due_soon(self):
        """Due within the next 3 days and not yet done."""
        if self.due_date and self.status != 'done':
            today = datetime.utcnow().date()
            return today <= self.due_date <= today + timedelta(days=3)
        return False


# ─── Database Initialization (Runs on both Local & Render) ─────────────────────

def seed_data():
    if Category.query.count() == 0:
        colors = ['#ef4444', '#f97316', '#10b981', '#6366f1', '#8b5cf6']
        names  = ['Work', 'Personal', 'Shopping', 'Health', 'Learning']
        cats   = [Category(name=n, color=c) for n, c in zip(names, colors)]
        db.session.add_all(cats)
        db.session.flush()

        samples = [
            Task(title='Set up project repository', description='Initialize Git repo and push to GitHub.',
                 priority='high', status='done', category_id=cats[0].id),
            Task(title='Write unit tests', description='Cover all controller methods.',
                 priority='high', status='in_progress', category_id=cats[0].id),
            Task(title='Buy groceries', description='Milk, eggs, bread, fruits.',
                 priority='medium', status='pending', category_id=cats[2].id),
            Task(title='Morning run', description='5 km run before breakfast.',
                 priority='low', status='pending', category_id=cats[3].id),
            Task(title='Read Flask docs', description='Go through blueprints section.',
                 priority='medium', status='pending', category_id=cats[4].id),
        ]
        db.session.add_all(samples)
        db.session.commit()

# This block forces table creation and seeding during Gunicorn startup on Render
with app.app_context():
    db.create_all()
    seed_data()


# ─── Routes: Home / Dashboard ──────────────────────────────────────────────────

@app.route('/')
def index():
    total      = Task.query.count()
    pending    = Task.query.filter_by(status='pending').count()
    in_prog    = Task.query.filter_by(status='in_progress').count()
    done       = Task.query.filter_by(status='done').count()
    all_tasks  = Task.query.all()
    overdue    = sum(1 for t in all_tasks if t.is_overdue())
    due_soon   = [t for t in all_tasks if t.is_due_soon()]
    recent     = Task.query.order_by(Task.created_at.desc()).limit(5).all()
    categories = Category.query.all()
    return render_template('index.html',
                           total=total, pending=pending,
                           in_prog=in_prog, done=done,
                           overdue=overdue, recent=recent,
                           due_soon=due_soon,
                           categories=categories)


# ─── Routes: Tasks ─────────────────────────────────────────────────────────────

@app.route('/tasks')
def tasks():
    search   = request.args.get('search', '')
    priority = request.args.get('priority', '')
    status   = request.args.get('status', '')
    cat_id   = request.args.get('category', '')
    sort     = request.args.get('sort', 'newest')   # newest | oldest | due | priority

    query = Task.query
    if search:
        query = query.filter(Task.title.ilike(f'%{search}%'))
    if priority:
        query = query.filter_by(priority=priority)
    if status:
        query = query.filter_by(status=status)
    if cat_id:
        query = query.filter_by(category_id=int(cat_id))

    # Sorting
    if sort == 'oldest':
        query = query.order_by(Task.created_at.asc())
    elif sort == 'due':
        query = query.order_by(Task.due_date.asc().nullslast())
    elif sort == 'priority':
        from sqlalchemy import case
        priority_order = case(
            (Task.priority == 'high',   1),
            (Task.priority == 'medium', 2),
            (Task.priority == 'low',    3),
            else_=4
        )
        query = query.order_by(priority_order)
    else:
        query = query.order_by(Task.created_at.desc())

    tasks_list = query.all()
    categories = Category.query.all()
    return render_template('tasks.html',
                           tasks=tasks_list, categories=categories,
                           search=search, priority=priority,
                           status=status, cat_id=cat_id, sort=sort)


@app.route('/tasks/new', methods=['GET', 'POST'])
def create_task():
    categories = Category.query.all()
    if request.method == 'POST':
        title       = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        priority    = request.form.get('priority', 'medium')
        status      = request.form.get('status', 'pending')
        due_str     = request.form.get('due_date', '')
        cat_id      = request.form.get('category_id') or None

        if not title:
            flash('Task title is required.', 'error')
            return render_template('task_form.html', categories=categories, task=None)

        due_date = datetime.strptime(due_str, '%Y-%m-%d').date() if due_str else None
        task = Task(title=title, description=description, priority=priority,
                    status=status, due_date=due_date, category_id=cat_id)
        db.session.add(task)
        db.session.commit()
        flash(f'Task "{title}" created successfully!', 'success')
        return redirect(url_for('tasks'))

    return render_template('task_form.html', categories=categories, task=None)


@app.route('/tasks/<int:task_id>')
def view_task(task_id):
    task = Task.query.get_or_404(task_id)
    return render_template('task_detail.html', task=task)


@app.route('/tasks/<int:task_id>/edit', methods=['GET', 'POST'])
def edit_task(task_id):
    task       = Task.query.get_or_404(task_id)
    categories = Category.query.all()
    if request.method == 'POST':
        task.title       = request.form.get('title', '').strip()
        task.description = request.form.get('description', '').strip()
        task.priority    = request.form.get('priority', 'medium')
        task.status      = request.form.get('status', 'pending')
        due_str          = request.form.get('due_date', '')
        cat_id           = request.form.get('category_id') or None

        if not task.title:
            flash('Task title is required.', 'error')
            return render_template('task_form.html', categories=categories, task=task)

        task.due_date    = datetime.strptime(due_str, '%Y-%m-%d').date() if due_str else None
        task.category_id = cat_id
        task.updated_at  = datetime.utcnow()
        db.session.commit()
        flash(f'Task "{task.title}" updated successfully!', 'success')
        return redirect(url_for('tasks'))

    return render_template('task_form.html', categories=categories, task=task)


@app.route('/tasks/<int:task_id>/delete', methods=['POST'])
def delete_task(task_id):
    task = Task.query.get_or_404(task_id)
    name = task.title
    db.session.delete(task)
    db.session.commit()
    flash(f'Task "{name}" deleted.', 'info')
    return redirect(url_for('tasks'))


@app.route('/tasks/<int:task_id>/toggle', methods=['POST'])
def toggle_task(task_id):
    task = Task.query.get_or_404(task_id)
    task.status = 'done' if task.status != 'done' else 'pending'
    db.session.commit()
    return jsonify({'status': task.status})


# ─── Routes: Categories ────────────────────────────────────────────────────────

@app.route('/categories')
def categories():
    cats = Category.query.order_by(Category.name).all()
    return render_template('categories.html', categories=cats)


@app.route('/categories/new', methods=['GET', 'POST'])
def create_category():
    if request.method == 'POST':
        name  = request.form.get('name', '').strip()
        color = request.form.get('color', '#6366f1')
        if not name:
            flash('Category name is required.', 'error')
            return render_template('category_form.html', category=None)
        if Category.query.filter_by(name=name).first():
            flash('A category with that name already exists.', 'error')
            return render_template('category_form.html', category=None)
        cat = Category(name=name, color=color)
        db.session.add(cat)
        db.session.commit()
        flash(f'Category "{name}" created!', 'success')
        return redirect(url_for('categories'))
    return render_template('category_form.html', category=None)


@app.route('/categories/<int:cat_id>/edit', methods=['GET', 'POST'])
def edit_category(cat_id):
    cat = Category.query.get_or_404(cat_id)
    if request.method == 'POST':
        name  = request.form.get('name', '').strip()
        color = request.form.get('color', '#6366f1')
        if not name:
            flash('Category name is required.', 'error')
            return render_template('category_form.html', category=cat)
        existing = Category.query.filter_by(name=name).first()
        if existing and existing.id != cat.id:
            flash('A category with that name already exists.', 'error')
            return render_template('category_form.html', category=cat)
        cat.name  = name
        cat.color = color
        db.session.commit()
        flash(f'Category "{name}" updated!', 'success')
        return redirect(url_for('categories'))
    return render_template('category_form.html', category=cat)


@app.route('/categories/<int:cat_id>/delete', methods=['POST'])
def delete_category(cat_id):
    cat = Category.query.get_or_404(cat_id)
    name = cat.name
    db.session.delete(cat)
    db.session.commit()
    flash(f'Category "{name}" and all its tasks deleted.', 'info')
    return redirect(url_for('categories'))


# ─── API endpoints ─────────────────────────────────────────────────────────────

@app.route('/api/stats')
def api_stats():
    return jsonify({
        'total':       Task.query.count(),
        'pending':     Task.query.filter_by(status='pending').count(),
        'in_progress': Task.query.filter_by(status='in_progress').count(),
        'done':        Task.query.filter_by(status='done').count(),
    })


# ─── Local Development Run ─────────────────────────────────────────────────────

if __name__ == '__main__':
    app.run(debug=True, port=5000)
