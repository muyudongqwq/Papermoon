class AttributeRank:
#这个类定义了基础属性和加符
    rank_table = {0:"-", 1:"E", 2:"D", 3:"C", 4:"B", 5:"A", 10:"EX"}
    MAX_PLUS = 2

    def __init__(self, value, plus=0):
        if isinstance(value, tuple): value, plus = value
        #此处先将(a,b)变为单一整形变量

        if not isinstance(value, int) : raise TypeError("属性Rank必须是整数")
        if value < 0 : raise ValueError("属性Rank不能小于0")
        if plus not in [0,1,2]: raise ValueError("加符数量不对")

        self.base_value = value
        self.modifier_bonus = 0
        self.temporary_multiplier = 1
        self.base_plus = plus
        self.plus_bonus = 0
        self.plus = self.plus_capacity
#校验属性Rank

    @property
    def value(self):
        return max(
            0,
            (self.base_value + self.modifier_bonus)
            * self.temporary_multiplier,
        )

    @value.setter
    def value(self, new_value):
        """兼容旧初始化/GM赋值；持续效果应使用modifier_bonus。"""
        if not isinstance(new_value, int):
            raise TypeError("属性Rank必须是整数")
        if new_value < 0:
            raise ValueError("属性Rank不能小于0")
        self.base_value = new_value

    def adjust_modifier_bonus(self, amount):
        if not isinstance(amount, int):
            raise TypeError("属性Rank修正必须是整数")
        old_value = self.value
        self.modifier_bonus += amount
        return self.value - old_value

    @property
    def plus_capacity(self):
        return min(
            self.MAX_PLUS,
            max(0, self.base_plus + self.plus_bonus),
        )

    def adjust_plus_bonus(self, amount):
        if not isinstance(amount, int):
            raise TypeError("加符修正值必须是整数")
        old_capacity = self.plus_capacity
        self.plus_bonus += amount
        new_capacity = self.plus_capacity
        if new_capacity > old_capacity:
            self.plus += new_capacity - old_capacity
        else:
            self.plus = min(self.plus, new_capacity)
        return new_capacity

    def reset_plus(self):
        self.plus = self.plus_capacity
        return self.plus

    def consume_plus(self, amount=1):
        if not isinstance(amount, int) or amount < 1:
            raise ValueError("消耗的加符数量必须是正整数")
        if self.plus < amount:
            return False
        self.plus -= amount
        return True

    def restore_plus(self, amount=1):
        if not isinstance(amount, int) or amount < 1:
            raise ValueError("恢复的加符数量必须是正整数")
        restored = min(amount, self.plus_capacity - self.plus)
        self.plus += restored
        return restored

    def __str__(self):
        return self.display()

    def display(self):
        if self.value in self.rank_table: rank = self.rank_table[self.value]
        elif 6 <= self.value <= 10: rank = f"A({self.value})"
        else: rank = f"Rank {self.value}"

        if self.plus == 1: rank +="+"
        elif self.plus ==2: rank +="++" 
        return rank
#加符表达

class FixedRank:
#这个类定义了宝具和天赋属性
      valid_rank = {"C", "B", "A", "EX", "GM"}

      def __init__(self, rank, plus = 0, allow_plus = True):
          if isinstance(rank, tuple): rank, plus = rank

          if rank not in self.valid_rank:raise ValueError("天赋Rank录入有误")
          if plus not in [0,1]: raise ValueError("只能有一个加符")
          if plus == 1: 
              if not allow_plus: raise ValueError("天赋不允许有加符")
              if rank not in ["C", "B", "A"]: raise ValueError("EX不允许有加符")

          self.rank = rank
          self.plus = plus

      def display(self):
          result = self.rank

          if self.plus == 1: result +="+"
          return result

      def __str__(self):return self.display()

class SkillRank:
#这个类定义了技能等级
      valid_rank = {"D", "E", "C", "B", "A", "EX", "GM"}

      def __init__(self, rank):
        if rank not in self.valid_rank:raise ValueError("技能Rank录入有误")
        self.rank = rank

      def __str__(self):return self.rank

class NobleRank:
#这个类定义了宝具等级
      valid_rank = {"C", "B", "A", "EX", "GM"}

      def __init__(self, rank, plus = 0):
          if rank not in self.valid_rank: raise ValueError("录入的宝具等级有误")
          if plus not in [0,1]: raise ValueError ("宝具最多只能有一个加符")
          if plus == 1:
             if rank not in ["C", "B", "A"]: raise ValueError ("EX宝具不适用加符")

          self.rank = rank
          self.plus = plus

      def display(self):
          result = self.rank

          if self.plus == 1: result +="+"
          return result

      def __str__(self): return self.rank
          

