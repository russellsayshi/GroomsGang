from flask import Flask, render_template, flash, redirect, request, abort, url_for, g
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField
from wtforms.validators import DataRequired
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
import datetime
from datetime import timedelta
import time
import json
import locale
import os

locale.setlocale(locale.LC_ALL, 'en_US.utf8')
roommates = ['Russell', 'Alex', 'Eli'] # do not change order
spending_types = ['grocery', 'rent', 'bill', 'maintenance', 'restaurant', 'furniture/appliance', 'fun', 'miscellaneous'] # all should be lowercase
payment_methods = ['venmo', 'cash', 'check', 'zelle', 'other'] # all should be lowercase
SECRET_KEY = os.urandom(32)
app = Flask(__name__, static_url_path='/static')
app.config['SECRET_KEY'] = SECRET_KEY
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
login_manager = LoginManager()
login_manager.init_app(app)
db = SQLAlchemy()
db.init_app(app)

@app.route('/')
@login_required
def index():
    return render_template('index.html', tab='home', title='Home', remaining_tasks=num_remaining_tasks(current_user.name), num_groceries=GroceryItem.query.filter_by(recently_bought=False).count())

@login_manager.unauthorized_handler
def unauthorized_callback():
    return redirect('/login?next=' + request.path)

class GroceryItem(db.Model):
    __tablename__ = 'grocery'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String)
    quantity = db.Column(db.Integer)
    note = db.Column(db.String)
    votes = db.Column(db.Integer, default=0)
    recently_bought = db.Column(db.Boolean, default=False)
    bought_by = db.Column(db.String)
    added_when = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    bought_when = db.Column(db.DateTime, default=datetime.datetime.utcnow)

class Receipt(db.Model):
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    added_when = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    itemdata = db.Column(db.String)
    image_file = db.Column(db.String)

class Purchase(db.Model):
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String)
    added_when = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    bought_when = db.Column(db.DateTime)
    bought_by = db.Column(db.Integer)
    bought_for = db.Column(db.Integer)
    spending_type = db.Column(db.String)
    price = db.Column(db.Float)
    totals = db.Column(db.String)
    split_mode = db.Column(db.String)
    receipt_id = db.Column(db.Integer, default=-1)
    additional_info = db.Column(db.String)

class MoneyTransfer(db.Model):
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String)
    who_paid = db.Column(db.Integer)
    amount = db.Column(db.Float)
    to_whom = db.Column(db.Integer)
    added_when = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    transferred_when = db.Column(db.DateTime)
    method = db.Column(db.String)
    additional_info = db.Column(db.String)

class WeeklyTasks(db.Model):
    __tablename__ = 'weekly_tasks'
    week_id = db.Column(db.Integer, primary_key=True)
    obj = db.Column(db.String)

class User(db.Model):
    __tablename__ = 'user'
    name = db.Column(db.String, primary_key=True)
    password = db.Column(db.String)
    authenticated = db.Column(db.Boolean, default=False)
    def is_active(self):
        return True
    def get_id(self):
        return self.name
    def is_authenticated(self):
        return self.authenticated
    def is_anonymous(self):
        return False

class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    remember_me = BooleanField('Remember Me')
    submit = SubmitField('Sign In')

def is_safe_url(url):
    return 'javascript' not in url.lower() and (url.lower().startswith('http://') or url.lower().startswith('https://') or url.lower().startswith('/'))

@app.route('/logout')
def logout():
    logout_user()
    flash('Logged out.')
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = user_loader(form.username.data)
        if user is not None and user.name == form.username.data and user.password == form.password.data:
            login_user(user, remember=form.remember_me.data)
            #flash("Logged in successfully.")
            next = request.args.get('next')
            if next is not None:
                if not is_safe_url(next):
                    return abort(400)
            return redirect(next or url_for('index'))
        else:
            return render_template('login.html', tab='login', form=form, error="Invalid credentials.")
    elif request.method.lower() == "post":
        return render_template('login.html', tab='login', form=form, error="Form not properly submitted.")
    else:
        return render_template('login.html', tab='login', form=form)

def fetch_task_names():
    tasks = []
    with open("tasks.txt", "r") as f:
        for line in f:
            tasks.append(line.strip())
    return tasks

def get_week_id():
    jan_4_1970 = 280800000 # jan 4 1970 in milliseconds
    current_time = int(round(time.time() * 1000)) # current time
    weeks_since = (current_time - jan_4_1970)/1000/60/60/24/7
    return int(weeks_since)

def fetch_task_obj(week, create_if_nonexistent=False):
    tasks = WeeklyTasks.query.get(week)
    if tasks is None:
        if create_if_nonexistent:
            last_week_tasks = fetch_task_obj(week-1, create_if_nonexistent=False)
            tasks = []
            task_names = fetch_task_names()
            for index, task_name in enumerate(task_names):
                assigned_to = roommates[(week + index) % len(roommates)] # generate roommate
                overdue = False

                # determine if roommate is overdue for this task from last week
                # if so, assign it to them this week as well
                if last_week_tasks is not None:
                    for last_week_task in last_week_tasks:
                        if last_week_task['name'].lower() == task_name.lower():
                            if last_week_task['completed'] == False:
                                assigned_to = last_week_task['assigned_to']
                                overdue = True
                            break

                # add task
                tasks.append({'id': index, 'name': task_name, 'assigned_to': assigned_to, 'completed': False, 'overdue': overdue})
            serialized_obj = json.dumps(tasks)
            print("Generating new tasks. Serialized: " + serialized_obj)
            db.session.add(WeeklyTasks(week_id=week, obj=serialized_obj))
            db.session.commit()
            return tasks
        else:
            return None
    else:
        return json.loads(tasks.obj)

def num_remaining_tasks(user):
    tasks = fetch_task_obj(get_week_id(), True)
    ntasks = 0
    for task in tasks:
        if not task['completed'] and task['assigned_to'].lower() == user.lower():
            ntasks += 1
    return ntasks

@app.route('/task/<action>/<week>/<id>')
@login_required
def modify_task_status(action, week, id):
    if not (action == "complete" or action == "uncomplete"):
        flash("Unknown action.")
        return redirect(url_for('tasks', week=week))

    tasks_db = WeeklyTasks.query.get(week)
    if tasks_db is None:
        flash('Nonexistent week.')
        return redirect(url_for('tasks', week=week))

    tasks = json.loads(tasks_db.obj)
    for task in tasks:
        if task['id'] == int(id):
            task['completed'] = True if action == "complete" else False
            tasks_db.obj = json.dumps(tasks)
            db.session.commit()
            return redirect(url_for('tasks', week=week))
    flash('Nonexistent task.')
    return redirect(url_for('tasks', week=week))

@app.route('/schedule')
@login_required
def schedule():
    return render_template('schedule.html', tab='schedule')

@app.route('/tasks/<week>')
@login_required
def tasks(week):
    if week == "latest" or week == str(get_week_id()):
        latest = True
        week = get_week_id()
        tasks = fetch_task_obj(week, True)
    else:
        try:
            week = int(week)
        except:
            abort(400)
            return
        latest = False
        tasks = fetch_task_obj(week, False)
    show_all = "show_all" in request.args
    if tasks is not None and not show_all:
        tasks = [task for task in tasks if task["assigned_to"].lower() == current_user.name.lower()]
    return render_template('tasks.html', tab='tasks', week=week, latest=latest, tasks=tasks, show_all=show_all)

@login_manager.user_loader
def user_loader(user_id):
    user = User.query.get(user_id)
    return user

@app.route('/groceries')
@login_required
def groceries():
    groceries = GroceryItem.query.all()

    # remove out of date groceries
    groceries_to_remove = []
    for grocery in groceries:
        if grocery.bought_when + timedelta(weeks=1) < datetime.datetime.now():
            # has been removed for more than a week
            with open("grocery_log.txt", "a") as f:
                f.write(str(grocery.id) + "," + grocery.name + "," + str(grocery.quantity) + "," + str(grocery.votes) + "," + str(grocery.recently_bought) + "," + grocery.bought_by + "," + str(grocery.added_when) + "," + str(grocery.bought_when) + "," + grocery.note + "\n")
            groceries_to_remove.append(grocery)
    if len(groceries_to_remove) > 0:
        for grocery in groceries_to_remove:
            db.session.delete(grocery)
        db.session.commit()
        print("Purged old groceries.")

    return render_template('groceries.html', tab='groceries', groceries=groceries, show_bought=('show_bought' in request.args))

@app.route('/groceries/add', methods=['GET', 'POST'])
@login_required
def add_grocery():
    if request.method != 'POST':
        return redirect(url_for('groceries'))
    name = request.form['name']
    if len(name.strip()) < 3:
        flash("Please add a name of at least 3 characters.")
        return redirect(url_for('groceries'))
    quantity = int(request.form['quantity'])
    note = request.form['note']
    votes = strings_to_votes([current_user.name])
    item = GroceryItem(name=name, quantity=quantity, note=note, votes=votes)
    db.session.add(item)
    db.session.commit()
    return redirect(url_for('groceries'))

@app.route('/groceries/<action>/<id>')
@login_required
def modify_grocery(action, id):
    if not (action == "delete" or action == "undelete" or action == "vote"):
        return abort(400)
    grocery = GroceryItem.query.get(id)
    if action == "undelete":
        grocery.recently_bought = False
    elif action == "delete":
        grocery.recently_bought = True
        grocery.bought_when = datetime.datetime.utcnow()
        grocery.bought_by = current_user.name
    elif action == "vote":
        for index, roommate in enumerate(roommates):
            if roommate.lower() == current_user.name.lower():
                if grocery.votes & (2 ** index) != 0:
                    grocery.votes = grocery.votes & ~(2 ** index)
                else:
                    grocery.votes = grocery.votes | (2 ** index)
    db.session.commit()
    return redirect(url_for('groceries'))

def votes_to_strings(votes):
    ret = []
    for index, roommate in enumerate(roommates):
        if votes & (2 ** index) != 0:
            ret.append(roommate.lower())
    return ret

def votes_to_string(votes):
    st = ""
    for index, roommate in enumerate(roommates):
        if votes & (2 ** index) != 0:
            st += roommate[0].upper()
    return st

def strings_to_votes(arr):
    votes = 0
    for name in arr:
        for index, roommate in enumerate(roommates):
            if roommate.lower() == name.lower():
                votes += 2 ** index
                break
    return votes

def capitalize(st):
    if len(st) >= 1:
        return st[0].upper() + st[1:]
    else:
        return st

def get_roommate_name(id):
    return roommates[id]

def money_format(num):
    return locale.currency(num)

def time_conv(time):
    return time - timedelta(hours=5)

@app.context_processor
def context():
    return dict(votes_to_string=votes_to_string, capitalize=capitalize, get_roommate_name=get_roommate_name, money_format=money_format, time_conv=time_conv, get_roommate_id=get_roommate_id, roommates=roommates)

def get_roommate_id(st):
    for id, roommate in enumerate(roommates):
        if roommate.lower() == st.lower():
            return id
    return None

def calc_totals(purchase):
    if purchase.split_mode == 'even':
        totals = []
        npeople = 0
        for index, roommate in enumerate(roommates):
            if purchase.bought_for & (2 ** index) != 0:
                totals.append(purchase.price)
                npeople += 1
            else:
                totals.append(0)
        for i in range(len(totals)):
            totals[i] = totals[i]/npeople
        purchase.totals = ",".join([str(x) for x in totals])
    else:
        raise("Unknown mode.")

@app.route('/owes')
@login_required
def show_owes():
    return str(calc_owes())

@app.route('/purchase/add', methods=['GET', 'POST'])
@login_required
def add_purchase():
    if request.method == 'GET':
        return render_template('new_purchase.html', tab='finance', date=f"{datetime.datetime.now():%Y-%m-%d}", spending_types=spending_types, roommates=roommates)
    elif request.method == 'POST':
        name = request.form['name']
        bought_when = datetime.datetime.strptime(request.form['bought_when'], '%Y-%m-%d')
        bought_by = get_roommate_id(request.form['bought_by'])
        bought_for = []
        for roommate in roommates:
            if 'buying_for_' + roommate.lower() in request.form:
                bought_for.append(roommate)
        bought_for = strings_to_votes(bought_for)
        assert(bought_for > 0)
        spending_type = request.form['spending_type']
        assert(spending_type.lower() in spending_types)
        price = float(request.form['price'])
        assert(price >= 0 and price < 5000)
        split_mode = request.form['split_mode']
        additional_info = request.form['additional_info']
        purchase = Purchase(name=name, bought_when=bought_when, bought_by=bought_by, bought_for=bought_for, spending_type=spending_type, price=price, split_mode=split_mode, additional_info=additional_info)
        calc_totals(purchase)
        db.session.add(purchase)
        db.session.commit()
        flash("Successfully added.")
        return redirect(url_for('finance'))

@app.route('/purchase/view/<id>')
@login_required
def view_purchase(id):
    if id == "all":
        return render_template("view_all_purchases.html", tab="finance", purchases=Purchase.query.order_by(Purchase.bought_when.desc(), Purchase.added_when.desc()).all())
    else:
        purchase = Purchase.query.get(int(id))
        if purchase == None:
            flash("Couldn't find that purchase.")
            return redirect(url_for('finance'))
        data = {
            'name': purchase.name,
            'bought_by': get_roommate_name(purchase.bought_by),
            'added_when': purchase.added_when,
            'additional_info': purchase.additional_info,
            'split_mode': purchase.split_mode,
            'price': purchase.price,
            'bought_for': ", ".join([capitalize(x) for x in votes_to_strings(purchase.bought_for)]),
            'bought_when': f"{purchase.bought_when:%Y-%m-%d}",
            'receipt_id': purchase.receipt_id,
            'totals': purchase.totals,
            'spending_type': purchase.spending_type,
        }
        return render_template('view_purchase.html', tab='finance', purchase=data, id=id)

@app.route('/purchase/edit/<id>', methods=['GET', 'POST'])
@login_required
def edit_purchase(id):
    purchase = Purchase.query.get(id)
    if request.method == 'GET':
        data = {
            'name': purchase.name,
            'bought_by': get_roommate_name(purchase.bought_by),
            'additional_info': purchase.additional_info,
            'split_mode': purchase.split_mode,
            'price': purchase.price,
            'bought_for': votes_to_strings(purchase.bought_for),
            'bought_when': f"{purchase.bought_when:%Y-%m-%d}",
            'totals': purchase.totals,
            'spending_type': purchase.spending_type,
        }
        return render_template('edit_purchase.html', tab='finance', data=data, can_delete=(data['bought_by'].lower() == current_user.name.lower()), id=id, roommates=roommates, spending_types=spending_types)
    else:
        if 'save' in request.form:
            name = request.form['name']
            bought_when = datetime.datetime.strptime(request.form['bought_when'], '%Y-%m-%d')
            bought_by = get_roommate_id(request.form['bought_by'])
            bought_for = []
            for roommate in roommates:
                if 'buying_for_' + roommate.lower() in request.form:
                    bought_for.append(roommate)
            bought_for = strings_to_votes(bought_for)
            assert(bought_for > 0)
            spending_type = request.form['spending_type']
            assert(spending_type.lower() in spending_types)
            price = float(request.form['price'])
            assert(price >= 0 and price < 5000)
            split_mode = request.form['split_mode']
            additional_info = request.form['additional_info']

            purchase.name = name
            purchase.bought_when = bought_when
            purchase.bought_for = bought_for
            purchase.spending_type = spending_type
            purchase.price = price
            purchase.split_mode = split_mode
            purchase.additional_info = additional_info
            calc_totals(purchase)
            db.session.commit()
            flash("Saved successfully.")
            return redirect(url_for('view_purchase', id=id))
        elif 'delete' in request.form:
            print("TODO log deletion and save copy of deleted purchase.")
            if get_roommate_name(purchase.bought_by).lower() == current_user.name.lower():
                db.session.delete(purchase)
                db.session.commit()
                flash("Deleted purchase id %s, '%s'." % (purchase.id, purchase.name))
                return redirect(url_for('finance', id=id))
            else:
                flash("You can only delete your own purchases.")
                return redirect(url_for('edit_purchase', id=id))
        else:
            return abort(400)

@app.route('/addusers')
def addusers():
    """
    MoneyTransfer.__table__.drop(db.engine)
    db.session.commit()
    db.create_all()
    """
    """
    db.create_all()
    db.session.delete(WeeklyTasks.query.get(2590))
    db.session.commit()
    """
    return "none"
    """
    russell = User(name='russell', password='hockey5485', authenticated=True)
    eli = User(name='eli', password='dingbat9824')
    alex = User(name='alex', password='kgb3762')
    db.create_all()
    db.session.add(russell)
    db.session.add(eli)
    db.session.add(alex)
    db.session.commit()
    """

@app.route('/moneytransfer/add', methods=['GET', 'POST'])
@login_required
def add_moneytransfer():
    if request.method == 'GET':
        return render_template('new_moneytransfer.html', date=f"{datetime.datetime.now():%Y-%m-%d}", tab='finance', roommates=roommates, methods=payment_methods)
    else:
        name = request.form["name"]
        try:
            amount = float(request.form["amount"])
        except:
            flash("Error parsing amount.")
            return redirect(url_for("add_moneytransfer"))
        additional_info = request.form["additional_info"]
        method = request.form["method"]
        to_whom = get_roommate_id(request.form["to_whom"])
        who_paid = get_roommate_id(request.form["who_paid"])
        if to_whom == None or who_paid == None:
            flash("Roomate invalid.")
            return redirect(url_for("add_moneytransfer"))
        if to_whom == who_paid:
            flash("Can't pay yourself.")
            return redirect(url_for("add_moneytransfer"))
        if amount <= 0:
            flash("Must pay a positive amount of money.")
            return redirect(url_for("add_moneytransfer"))
        if amount > 5000:
            flash("Too much money. Check for typos.")
            return redirect(url_for("add_moneytransfer"))
        try:
            transferred_when = datetime.datetime.strptime(request.form['transferred_when'], '%Y-%m-%d')
        except:
            flash("Could not parse date.")
            return redirect(url_for("add_moneytransfer"))

        mtransfer = MoneyTransfer(name=name, amount=amount, additional_info=additional_info, method=method, to_whom=to_whom, who_paid=who_paid, transferred_when=transferred_when)
        db.session.add(mtransfer)
        db.session.commit()
        flash("Added.")
        return redirect(url_for("finance"))

def calc_owes():
    purchases = Purchase.query.all()
    money_transfers = MoneyTransfer.query.all()

    #owes[a][b] is how much a owes to b
    owes = []
    for roommate in roommates:
        owes.append([0] * len(roommates))
    for purchase in purchases:
        totals = [float(x) for x in purchase.totals.split(",")]
        for index, amt in enumerate(totals):
            owes[index][purchase.bought_by] += amt
    for money_transfer in money_transfers:
        owes[money_transfer.to_whom][money_transfer.who_paid] += money_transfer.amount
    for who_owes in range(len(roommates)):
        for who_is_owed in range(len(roommates)):
            if who_owes != who_is_owed:
                # in case two people owe each other money, subtract out the minimum
                amt_to_subtract = min(owes[who_owes][who_is_owed], owes[who_is_owed][who_owes])
                owes[who_owes][who_is_owed] -= amt_to_subtract
                owes[who_is_owed][who_owes] -= amt_to_subtract

    return owes

@app.route('/finance')
@login_required
def finance():
    recent_purchases = Purchase.query.order_by(Purchase.bought_when.desc(), Purchase.added_when.desc()).limit(20).all()
    recent_moneytransfers = MoneyTransfer.query.order_by(MoneyTransfer.transferred_when.desc()).limit(10).all()
    owes = calc_owes()
    return render_template('finance.html', recent_purchases=recent_purchases, recent_moneytransfers=recent_moneytransfers, owes=owes, tab='finance')

@app.route('/moneytransfer/view/<id>')
@login_required
def view_moneytransfer(id):
    if id == "all":
        return render_template("view_all_moneytransfers.html", tab="finance", money_transfers=MoneyTransfer.query.order_by(MoneyTransfer.transferred_when.desc(), MoneyTransfer.added_when.desc()).all())
    else:
        money_transfer = MoneyTransfer.query.get(int(id))
        if money_transfer == None:
            flash("Couldn't find that money transfer.")
            return redirect(url_for('finance'))
        data = {
            'name': money_transfer.name,
            'who_paid': get_roommate_name(money_transfer.who_paid),
            'to_whom': get_roommate_name(money_transfer.to_whom),
            'additional_info': money_transfer.additional_info,
            'method': money_transfer.method,
            'amount': money_transfer.amount,
            'transferred_when': f"{money_transfer.transferred_when:%Y-%m-%d}",
            'added_when': time_conv(money_transfer.added_when),
        }
        return render_template('view_moneytransfer.html', tab='finance', money_transfer=data, id=id)

@app.route('/moneytransfer/edit/<id>', methods=['GET', 'POST'])
@login_required
def edit_moneytransfer(id):
    money_transfer = MoneyTransfer.query.get(int(id))
    if request.method == 'GET':
        data = {
            'name': money_transfer.name,
            'who_paid': get_roommate_name(money_transfer.who_paid),
            'to_whom': get_roommate_name(money_transfer.to_whom),
            'additional_info': money_transfer.additional_info,
            'method': money_transfer.method,
            'amount': money_transfer.amount,
            'transferred_when': f"{money_transfer.transferred_when:%Y-%m-%d}",
        }
        return render_template('edit_moneytransfer.html', tab='finance', data=data, can_delete=(data['who_paid'].lower() == current_user.name.lower()), id=id, roommates=roommates, methods=payment_methods)
    else:
        if 'save' in request.form:
            name = request.form["name"]
            try:
                amount = float(request.form["amount"])
            except:
                flash("Error parsing amount.")
                return redirect(url_for("add_moneytransfer"))
            additional_info = request.form["additional_info"]
            method = request.form["method"]
            to_whom = get_roommate_id(request.form["to_whom"])
            who_paid = get_roommate_id(request.form["who_paid"])
            if to_whom == None or who_paid == None:
                flash("Roomate invalid.")
                return redirect(url_for("add_moneytransfer"))
            if to_whom == who_paid:
                flash("Can't pay yourself.")
                return redirect(url_for("add_moneytransfer"))
            if amount <= 0:
                flash("Must pay a positive amount of money.")
                return redirect(url_for("add_moneytransfer"))
            if amount > 5000:
                flash("Too much money. Check for typos.")
                return redirect(url_for("add_moneytransfer"))
            try:
                transferred_when = datetime.datetime.strptime(request.form['transferred_when'], '%Y-%m-%d')
            except:
                flash("Could not parse date.")
                return redirect(url_for("add_moneytransfer"))

            money_transfer.name = name
            money_transfer.method = method
            money_transfer.to_whom = to_whom
            money_transfer.who_paid = who_paid
            money_transfer.additional_info = additional_info
            money_transfer.amount = amount
            money_transfer.transferred_when = transferred_when

            db.session.commit()
            flash("Saved successfully.")
            return redirect(url_for('view_moneytransfer', id=id))
        elif 'delete' in request.form:
            print("TODO log deletion and save copy of deleted money transfer.")
            if get_roommate_name(money_transfer.who_paid).lower() == current_user.name.lower():
                db.session.delete(money_transfer)
                db.session.commit()
                flash("Deleted money transfer id %s, '%s'." % (money_transfer.id, money_transfer.name))
                return redirect(url_for('finance', id=id))
            else:
                flash("You can only delete your own money transfers.")
                return redirect(url_for('edit_moneytransfer', id=id))
        else:
            return abort(400)

"""
@app.context_processor
def inject_week():
    return dict(week=get_week_id())
"""

@app.before_request
def before_request():
    g.start = time.time()

@app.after_request
def after_request(response):
    diff = time.time() - g.start
    if ((response.response) and
        (200 <= response.status_code < 300) and
        (response.content_type.startswith('text/html'))):
        response.set_data(response.get_data().replace(
            b'__EXECUTION_TIME__', bytes(str(diff), 'utf-8')))
    return response

app.run()

