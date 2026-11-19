"""Locate checklist controls in the accepted form or an older cached layout."""

def elements(card):
    for block in card['body']['elements']:
        if block.get('tag')=='form':return block['elements']
        if block.get('element_id')=='todo_list':return block['columns'][0]['elements']
    raise ValueError('Checklist container was not found')
