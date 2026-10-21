"""Safe local arithmetic and explicit business commands independent of model tool syntax."""
import ast,math,operator,re,json
BINARY={ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,ast.Div:operator.truediv,ast.FloorDiv:operator.floordiv,ast.Mod:operator.mod,ast.Pow:operator.pow}
def calculate(expression):
    if not isinstance(expression,str) or not 1<=len(expression)<=200:raise ValueError('计算式长度须为1~200字符')
    tree=ast.parse(expression,mode='eval')
    if sum(1 for _ in ast.walk(tree))>80:raise ValueError('计算式过于复杂')
    def visit(node,depth=0):
        if depth>16:raise ValueError('计算式嵌套过深')
        if isinstance(node,ast.Constant) and type(node.value) in (int,float):v=node.value
        elif isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):v=visit(node.operand,depth+1)*(1 if isinstance(node.op,ast.UAdd) else -1)
        elif isinstance(node,ast.BinOp) and type(node.op) in BINARY:
            a,b=visit(node.left,depth+1),visit(node.right,depth+1)
            if isinstance(node.op,ast.Pow) and (abs(b)>12 or a<0 and b!=int(b)):raise ValueError('指数超出限制')
            v=BINARY[type(node.op)](a,b)
        else:raise ValueError('仅支持数字、括号和四则运算、取余、有限次幂')
        if type(v) not in (int,float) or not math.isfinite(v) or abs(v)>1e100:raise ValueError('计算结果超出范围')
        return v
    v=visit(tree.body)
    return str(v) if isinstance(v,int) else format(v,'.12g')
def arithmetic_input(text):
    s=text.strip().replace('×','*').replace('÷','/').replace('＝','=').rstrip('=？?')
    s=re.sub(r'^(请帮我计算|帮我计算|计算|算一下)\s*[:：]?\s*','',s)
    return s if re.fullmatch(r'[\d.\s+*/%()\-]+',s) and re.search(r'\d',s) and re.search(r'[+*/%\-]',s) else None
