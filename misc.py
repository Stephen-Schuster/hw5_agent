
# this was used to make it so each number was separated by new lines rather than spaces
with open('ans','r') as f:
    content = f.read()

with open('ans','w') as f:
    f.write('\n'.join(content.split()))