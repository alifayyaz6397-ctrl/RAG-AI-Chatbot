from fastapi import FastAPI
# import requests
app=FastAPI()
# @app.get("/square/{num}")
# def square(num: int):
#     return {"Square": num * num}
# def fun():
#     print("hello")
# x=fun
# x()
# def hell():
#     print("hell")
#     return fun()
# # hell()
# def my_decorator(func1,func2):
#     def wrapper():
#         print("Starting...")
#         func1()
#         func2
#     return wrapper

    
# def hello():
#     print("hello")
# hello=my_decorator(hello)
# hello()
# @my_decorator
# def hello():
#     print("hello")
# hello()
# def helloworld():
#     print('hi')
# @app.get("/")
# def hello():
#     print("i am on terminal")
#     return "hello"
# @app.get("/square/{num}")
# def square(num:int):
#     return {"square" : num*num}
@app.post("/chatbot")
def print(num:int):
    return num*num
