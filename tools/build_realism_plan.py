"""Build an invented, versioned scenario inventory. Never reads private email."""
import argparse,json
from pathlib import Path
LABELS=['correspondence','transactions/records','alerts/updates','newsletters/publications','promotions/outreach','community/discussions','scheduling/invitations']
C,T,A,N,P,G,S=LABELS
SCENARIOS=[
('application-received',[A],'Automatic receipt of a job application; courteous thanks, no interview arranged.'),
('application-rejected',[A],'Automatic rejection after review; warm encouragement and a small careers footer, no substantive individual feedback.'),
('application-record',[A,T],'Successful submission with a retained copy of application fields and a long invented resume; the included cover letter is record content.'),
('personal-feedback',[C,A],'Recruiter gives individualized feedback and clarification about a candidacy, with a stale quoted interview invitation; no new meeting request.'),
('meeting-recap',[A],'Recorder service reports notes ready for a completed meeting; mentions being invited to record, discussion topics, counts and old date; no invitation now.'),
('community-recap',[A],'Automatic recording-ready notice for a completed club gathering; group topic and discussion counts do not make it current participation.'),
('meeting-confirmation',[A,S],'Confirms a concrete future interview slot with location and calendar links; no personal exchange beyond mechanics.'),
('meeting-reminder',[A,S],'Reminder to join a booked future meeting, concrete date and join link.'),
('meeting-reschedule',[A,S],'A currently booked appointment changed time; calendar notification and RSVP action.'),
('routine-slot',[S],'Short human reply agreeing a meeting slot, with friendly greeting and signature; no substantive advice or personal exchange.'),
('calendar-signature',[C],'Substantive individual clarification with generic calendar link in signature; historical meeting request quoted, no current invitation.'),
('task-deadline',[A],'Task system lists overdue tasks and due dates with links; deadlines are not invitations.'),
('connection-failed',[A],'Calendar integration lost authentication; reconnect instructions, no actual meeting scheduling.'),
('delivery-failure',[A],'Delivery failure with SMTP diagnostics, error code and recipient; no interpersonal conversation.'),
('security-report',[A],'Automated message-authentication aggregate report with short explanatory body and named compressed attachment; do not invent attachment contents.'),
('security-report-subject',[A],'Empty body, informative subject identifying domain-authentication aggregate report, invented report IDs and example.org domain.'),
('ambiguous-attachment',[],'Subject is Document, body says See attached; absent attachment content makes relevant categories unknown; do not force all-negative.'),
('scheduled-subject',[A,S],'Empty body with subject stating a new concrete webinar invitation and specific future date/time; evidence only in subject.'),
('statement-available',[A,T],'Bank account statement available with statement date and masked account; long legal footer is not marketing.'),
('paid-receipt',[A,T],'Payment completed with amount paid, receipt number and invoice lines; include subscription management link.'),
('renewal-reminder',[A,T],'Account subscription will renew on a future date; amount due and payment update link, no payment completed yet.'),
('report-confirmation',[A],'Trust/safety service requests confirmation of a filed abuse report; community word appears but no group discussion.'),
('password-reset',[A],'Password reset notification with expiry and long legal/security footer.'),
('service-change',[A],'Mandatory subprocessors or service policy update notice; conversational wording but no marketing offer.'),
('product-changelog',[A,N],'Curated release changelog announcing multiple shipped product changes; no upsell and no event invitation.'),
('editorial-article',[N],'Delivered long original editorial article with headings and recurring publication identity; modest related-reading, share and unsubscribe footer, no substantive pitch.'),
('newsletter-events',[N,S],'Recurring curated bulletin with editorial updates and several concrete future event invitations; ordinary subscription footer.'),
('marketing-report',[P],'Persuasive campaign asking reader to register for an upcoming research report; preview benefits, no delivered substantive editorial article.'),
('consultation-outreach',[P,S],'Individualized solicitation to accept a specific paid expert consultation; price offer not a completed receipt, long compliance footer.'),
('community-discussion',[G],'Member contributes arguments and questions to an ongoing group discussion, no event and no pitch; a normal name/signature not personal correspondence.'),
('personal-news',[C],'Friend shares substantive personal news and asks for individual advice; no business solicitation or event.'),
('no-purpose',[],'Message is a fragment or simple document title with readable content but genuinely no communicative purpose in this taxonomy; avoid turning unreadability into absence.')]
CONTEXTS=[('arts nonprofit','membership and volunteer coordination','bulleted web-to-text layout with repeated links and copyright footer'),('field equipment company','maintenance and logistics','plain text with wrapped lines, automated footer and support links'),('education cooperative','courses and enrollment','Unicode punctuation, mild HTML entity artifacts and short signature'),('small research studio','research operations','conversational wording, separate subject and realistic quoted prior messages'),('regional housing service','tenant and account operations','formal template with boilerplate, dates, identifiers and account links')]
def inventory():
 families=[]
 for kind,labels,purpose in SCENARIOS:
  for j,(sector,workflow,style) in enumerate(CONTEXTS):
   length='Keep body empty; put observable evidence only in subject.' if kind in {'security-report-subject','scheduled-subject'} else 'Use 2800-5500 bytes of meaningful prose, records or realistic quoted history, not repeated padding.' if kind in {'application-record','calendar-signature','personal-feedback','editorial-article','consultation-outreach','product-changelog'} else 'Vary body between 180 and 2200 bytes; avoid contrived label-signalling wording.'
   families.append({'family_id':f'r02-{kind}-{j}','case':'missing_context' if kind=='ambiguous-attachment' else 'no_match_candidate' if kind=='no-purpose' else 'single' if len(labels)==1 else 'overlap','intended_labels':labels,'topic':sector+' '+workflow,'context':f'Invent an email in a {sector} serving {workflow}. Situation: {purpose} Change people, organizations, identifiers, dates and circumstances independently; do not reuse any real message. Domain must be example.org.','purpose':purpose,'writing_style':style+'. '+length,'slice':'uncertainty' if kind=='ambiguous-attachment' else 'challenge','stratum':kind,'diagnostic_tags':[kind,'mail-realism-v1']})
 return {'schema_version':1,'families':families,'diversity':{'description':'32 communicative situations crossed with five different institutional workflows and delivery styles; variants stay within family; fresh invented text, no private examples.'}}
def main():
 p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);args=p.parse_args();args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(inventory(),indent=2)+'\n')
if __name__=='__main__':main()
