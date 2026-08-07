"""单例模式装饰器

用法:
    @singleton
    class MyClass:
        pass

    a = MyClass()
    b = MyClass()
    assert a is b  # True
"""
import functools
import threading


def singleton(cls):
    """线程安全的单例装饰器

    被装饰的类在首次实例化后，后续所有实例化都返回同一个对象。
    __init__ 仍会被每次调用，若需要只初始化一次，请在类内部用
    self._initialized 标志位控制（参考 DatabaseManager 的实现）。
    """
    instances = {}
    lock = threading.Lock()

    @functools.wraps(cls)
    def get_instance(*args, **kwargs):
        if cls not in instances:
            with lock:
                if cls not in instances:
                    instances[cls] = cls(*args, **kwargs)
        return instances[cls]

    # 保留对原始类的引用，便于测试时重置单例
    get_instance._instances = instances
    get_instance._cls = cls
    return get_instance
